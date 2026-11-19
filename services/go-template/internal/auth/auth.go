// Package auth implements the KARPY-HMAC-SHA256-V1 service request signature
// (see services/contracts/signing.md): signing for callers and a verifying
// HTTP middleware for services.
package auth

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"time"
)

const (
	Scheme          = "KARPY-HMAC-SHA256-V1"
	HeaderKeyID     = "X-Karpy-Key-Id"
	HeaderTimestamp = "X-Karpy-Timestamp"
	HeaderNonce     = "X-Karpy-Nonce"
	HeaderSignature = "X-Karpy-Signature"
	signaturePrefix = "v1="
	// MinSecretBytes is the minimum accepted shared-secret length.
	MinSecretBytes = 32
)

var (
	// ErrUnauthorized covers every authentication failure. The wrapped reason is
	// for server-side logs only and must never be returned to the caller.
	ErrUnauthorized = errors.New("invalid service authentication")
	// ErrReplay means the signature was valid but the nonce was already used.
	ErrReplay = errors.New("service request replayed")
	// ErrBodyTooLarge means the body exceeded the configured limit.
	ErrBodyTooLarge = errors.New("request body too large")

	keyIDPattern = regexp.MustCompile(`^[A-Za-z0-9._-]{1,64}$`)
	noncePattern = regexp.MustCompile(`^[A-Za-z0-9_-]{16,128}$`)
)

// ValidKeyID reports whether id is an acceptable key identifier.
func ValidKeyID(id string) bool { return keyIDPattern.MatchString(id) }

// CanonicalString builds the exact string that is signed.
func CanonicalString(keyID, method, pathAndQuery, timestamp, nonce string, body []byte) string {
	digest := sha256.Sum256(body)
	return strings.Join([]string{
		Scheme, keyID, strings.ToUpper(method), pathAndQuery, timestamp, nonce, hex.EncodeToString(digest[:]),
	}, "\n")
}

// Signature returns the X-Karpy-Signature header value ("v1=<hex>").
func Signature(secret []byte, canonical string) string {
	mac := hmac.New(sha256.New, secret)
	_, _ = mac.Write([]byte(canonical))
	return signaturePrefix + hex.EncodeToString(mac.Sum(nil))
}

// PathAndQuery renders the origin-form request target of u (escaped path plus
// raw query) without any normalisation.
func PathAndQuery(u *url.URL) string {
	p := u.EscapedPath()
	if p == "" {
		p = "/"
	}
	if u.RawQuery != "" {
		p += "?" + u.RawQuery
	}
	return p
}

// requestTarget is what the server signs over: the raw request-line target
// when available (exactly what the client sent), else the parsed URL.
func requestTarget(r *http.Request) string {
	if strings.HasPrefix(r.RequestURI, "/") {
		return r.RequestURI
	}
	return PathAndQuery(r.URL)
}

// SignRequest sets the four X-Karpy-* headers on an outbound request. body must
// be the exact bytes that will be sent. Use a fresh random nonce per request.
func SignRequest(r *http.Request, keyID string, secret []byte, body []byte, now time.Time, nonce string) {
	ts := strconv.FormatInt(now.Unix(), 10)
	canonical := CanonicalString(keyID, r.Method, PathAndQuery(r.URL), ts, nonce, body)
	r.Header.Set(HeaderKeyID, keyID)
	r.Header.Set(HeaderTimestamp, ts)
	r.Header.Set(HeaderNonce, nonce)
	r.Header.Set(HeaderSignature, Signature(secret, canonical))
}

// Verifier checks signed requests against a set of keys (several keys are
// accepted at once to allow rotation).
type Verifier struct {
	keys         map[string][]byte
	maxSkew      time.Duration
	replays      ReplayCache
	maxBodyBytes int64
	// Now is the clock; replaceable in tests.
	Now func() time.Time
}

// NewVerifier validates its inputs and copies the key material.
func NewVerifier(keys map[string][]byte, maxSkew time.Duration, maxBodyBytes int64, replays ReplayCache) (*Verifier, error) {
	if len(keys) == 0 || maxSkew <= 0 || maxBodyBytes <= 0 || replays == nil {
		return nil, errors.New("verifier requires keys, a positive skew window, a body limit and a replay cache")
	}
	copied := make(map[string][]byte, len(keys))
	for id, secret := range keys {
		if !ValidKeyID(id) || len(secret) < MinSecretBytes {
			return nil, fmt.Errorf("invalid service key %q", id)
		}
		copied[id] = append([]byte(nil), secret...)
	}
	return &Verifier{keys: copied, maxSkew: maxSkew, replays: replays, maxBodyBytes: maxBodyBytes, Now: time.Now}, nil
}

func unauthorized(reason string) error { return fmt.Errorf("%w: %s", ErrUnauthorized, reason) }

// Verify checks one request. It returns the key id that signed it.
func (v *Verifier) Verify(ctx context.Context, method, pathAndQuery string, h http.Header, body []byte) (string, error) {
	keyID, ts, nonce, sig := h.Get(HeaderKeyID), h.Get(HeaderTimestamp), h.Get(HeaderNonce), h.Get(HeaderSignature)
	if keyID == "" || ts == "" || nonce == "" || sig == "" {
		return "", unauthorized("missing signing header")
	}
	secret, ok := v.keys[keyID]
	if !ok {
		return "", unauthorized("unknown key id")
	}
	if len(ts) > 12 || strings.TrimLeft(ts, "0123456789") != "" {
		return "", unauthorized("malformed timestamp")
	}
	unix, err := strconv.ParseInt(ts, 10, 64)
	if err != nil {
		return "", unauthorized("malformed timestamp")
	}
	skew := v.Now().Sub(time.Unix(unix, 0))
	if skew > v.maxSkew || -skew > v.maxSkew {
		return "", unauthorized("timestamp outside skew window")
	}
	if !noncePattern.MatchString(nonce) {
		return "", unauthorized("malformed nonce")
	}
	if !strings.HasPrefix(sig, signaturePrefix) {
		return "", unauthorized("unsupported signature version")
	}
	provided, err := hex.DecodeString(strings.TrimPrefix(sig, signaturePrefix))
	if err != nil || len(provided) != sha256.Size {
		return "", unauthorized("malformed signature")
	}
	mac := hmac.New(sha256.New, secret)
	_, _ = mac.Write([]byte(CanonicalString(keyID, method, pathAndQuery, ts, nonce, body)))
	if !hmac.Equal(provided, mac.Sum(nil)) { // constant time
		return "", unauthorized("signature mismatch")
	}
	// Reserve only after the signature is valid, so unauthenticated callers
	// cannot fill the cache. TTL covers the whole window the timestamp is valid.
	fresh, err := v.replays.Reserve(ctx, keyID+"\x00"+nonce, 2*v.maxSkew)
	if err != nil {
		return "", fmt.Errorf("replay cache: %w", err)
	}
	if !fresh {
		return "", ErrReplay
	}
	return keyID, nil
}

type ctxKey struct{}

// KeyIDFromContext returns the key id that authenticated the request.
func KeyIDFromContext(ctx context.Context) string {
	id, _ := ctx.Value(ctxKey{}).(string)
	return id
}

// ErrorWriter writes the service's JSON error shape.
type ErrorWriter func(w http.ResponseWriter, r *http.Request, status int, code, message string)

// Middleware verifies the signature before calling next. The body is read
// (bounded), verified, and replaced so handlers can read it again.
func (v *Verifier) Middleware(log *slog.Logger, writeError ErrorWriter) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			body, err := io.ReadAll(http.MaxBytesReader(w, r.Body, v.maxBodyBytes))
			if err != nil {
				var tooLarge *http.MaxBytesError
				if errors.As(err, &tooLarge) {
					writeError(w, r, http.StatusRequestEntityTooLarge, "payload_too_large", "Request body is too large.")
					return
				}
				writeError(w, r, http.StatusBadRequest, "invalid_request", "Request body could not be read.")
				return
			}
			keyID, err := v.Verify(r.Context(), r.Method, requestTarget(r), r.Header, body)
			switch {
			case err == nil:
			case errors.Is(err, ErrReplay):
				log.WarnContext(r.Context(), "service request replayed", "key_id", r.Header.Get(HeaderKeyID))
				writeError(w, r, http.StatusConflict, "request_replayed", "Request was already processed.")
				return
			case errors.Is(err, ErrUnauthorized):
				log.WarnContext(r.Context(), "service authentication failed", "reason", err.Error(), "key_id", r.Header.Get(HeaderKeyID))
				writeError(w, r, http.StatusUnauthorized, "unauthorized", "Invalid service authentication.")
				return
			default:
				log.ErrorContext(r.Context(), "service authentication unavailable", "error", err)
				writeError(w, r, http.StatusServiceUnavailable, "auth_unavailable", "Authentication is temporarily unavailable.")
				return
			}
			r.Body = io.NopCloser(bytes.NewReader(body))
			next.ServeHTTP(w, r.WithContext(context.WithValue(r.Context(), ctxKey{}, keyID)))
		})
	}
}
