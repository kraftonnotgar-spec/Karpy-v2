package auth

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"
)

// Shared conformance vectors live in services/contracts so every language
// checks against the same file.
var vectorsPath = filepath.Join("..", "..", "..", "contracts", "signing-vectors.json")

type vector struct {
	Name            string `json:"name"`
	KeyID           string `json:"key_id"`
	Secret          string `json:"secret"`
	Method          string `json:"method"`
	PathAndQuery    string `json:"path_and_query"`
	Timestamp       string `json:"timestamp"`
	Nonce           string `json:"nonce"`
	Body            string `json:"body"`
	CanonicalString string `json:"canonical_string"`
	SignatureHeader string `json:"signature_header"`
}

func loadVectors(t *testing.T) []vector {
	t.Helper()
	raw, err := os.ReadFile(vectorsPath)
	if err != nil {
		t.Fatalf("read shared vectors %s: %v", vectorsPath, err)
	}
	var doc struct {
		Scheme  string   `json:"scheme"`
		Vectors []vector `json:"vectors"`
	}
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatal(err)
	}
	if doc.Scheme != Scheme || len(doc.Vectors) == 0 {
		t.Fatalf("unexpected vectors file: scheme %q, %d vectors", doc.Scheme, len(doc.Vectors))
	}
	return doc.Vectors
}

// Pinned copy of vector 1 so an accidental edit of the JSON is caught too.
const pinnedVector1 = "v1=52dab664eee3776e6b6a4cdf9985636a6f9b07eb68e8d54231baf005b978dec6"

func TestCanonicalStringAndSignatureMatchSharedVectors(t *testing.T) {
	vs := loadVectors(t)
	if vs[0].SignatureHeader != pinnedVector1 {
		t.Fatalf("vector 1 changed: %s", vs[0].SignatureHeader)
	}
	for _, v := range vs {
		got := CanonicalString(v.KeyID, v.Method, v.PathAndQuery, v.Timestamp, v.Nonce, []byte(v.Body))
		if got != v.CanonicalString {
			t.Errorf("%s canonical:\n got %q\nwant %q", v.Name, got, v.CanonicalString)
		}
		if sig := Signature([]byte(v.Secret), got); sig != v.SignatureHeader {
			t.Errorf("%s signature: got %s want %s", v.Name, sig, v.SignatureHeader)
		}
	}
}

func TestSignRequestProducesVectorHeaders(t *testing.T) {
	for _, v := range loadVectors(t) {
		r := httptest.NewRequest(v.Method, "http://svc.internal"+v.PathAndQuery, strings.NewReader(v.Body))
		unix, _ := strconv.ParseInt(v.Timestamp, 10, 64)
		SignRequest(r, v.KeyID, []byte(v.Secret), []byte(v.Body), time.Unix(unix, 0), v.Nonce)
		if got := r.Header.Get(HeaderSignature); got != v.SignatureHeader {
			t.Errorf("%s: got %s want %s", v.Name, got, v.SignatureHeader)
		}
	}
}

// --- middleware -----------------------------------------------------------

type harness struct {
	handler http.Handler
	v       vector
	now     time.Time
}

func newHarness(t *testing.T) *harness {
	t.Helper()
	vs := loadVectors(t)
	keys := map[string][]byte{}
	for _, v := range vs {
		keys[v.KeyID] = []byte(v.Secret)
	}
	unix, _ := strconv.ParseInt(vs[0].Timestamp, 10, 64)
	now := time.Unix(unix, 0)
	cache := NewMemoryReplayCache()
	cache.Now = func() time.Time { return now }
	verifier, err := NewVerifier(keys, 300*time.Second, 1<<20, cache)
	if err != nil {
		t.Fatal(err)
	}
	verifier.Now = func() time.Time { return now }
	writeErr := func(w http.ResponseWriter, _ *http.Request, status int, code, _ string) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(status)
		_ = json.NewEncoder(w).Encode(map[string]any{"error": map[string]string{"code": code}})
	}
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		_, _ = w.Write([]byte(KeyIDFromContext(r.Context()) + "|" + string(body)))
	})
	log := slog.New(slog.NewTextHandler(io.Discard, nil))
	return &harness{handler: verifier.Middleware(log, writeErr)(next), v: vs[0], now: now}
}

func (h *harness) request(mutate func(*http.Request)) *httptest.ResponseRecorder {
	r := httptest.NewRequest(h.v.Method, h.v.PathAndQuery, strings.NewReader(h.v.Body))
	r.Header.Set(HeaderKeyID, h.v.KeyID)
	r.Header.Set(HeaderTimestamp, h.v.Timestamp)
	r.Header.Set(HeaderNonce, h.v.Nonce)
	r.Header.Set(HeaderSignature, h.v.SignatureHeader)
	if mutate != nil {
		mutate(r)
	}
	rec := httptest.NewRecorder()
	h.handler.ServeHTTP(rec, r)
	return rec
}

func errorCode(t *testing.T, rec *httptest.ResponseRecorder) string {
	t.Helper()
	var body struct {
		Error struct {
			Code string `json:"code"`
		} `json:"error"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("not a JSON error: %q", rec.Body.String())
	}
	return body.Error.Code
}

func TestMiddlewareAcceptsValidSignatureAndRestoresBody(t *testing.T) {
	h := newHarness(t)
	rec := h.request(nil)
	if rec.Code != http.StatusOK {
		t.Fatalf("status %d body %s", rec.Code, rec.Body)
	}
	if want := h.v.KeyID + "|" + h.v.Body; rec.Body.String() != want {
		t.Fatalf("got %q want %q", rec.Body.String(), want)
	}
}

func TestMiddlewareRejectsBadSignature(t *testing.T) {
	h := newHarness(t)
	rec := h.request(func(r *http.Request) {
		r.Header.Set(HeaderSignature, "v1="+strings.Repeat("0", 64))
	})
	if rec.Code != http.StatusUnauthorized || errorCode(t, rec) != "unauthorized" {
		t.Fatalf("status %d body %s", rec.Code, rec.Body)
	}
}

func TestMiddlewareRejectsTamperedBodyAndPath(t *testing.T) {
	cases := map[string]func(*http.Request){
		"body":   func(r *http.Request) { r.Body = io.NopCloser(strings.NewReader(`{"message":"HELLO"}`)) },
		"query":  func(r *http.Request) { r.RequestURI = "/v1/echo?lang=fr" },
		"method": func(r *http.Request) { r.Method = http.MethodPut },
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			if rec := newHarness(t).request(mutate); rec.Code != http.StatusUnauthorized {
				t.Fatalf("status %d", rec.Code)
			}
		})
	}
}

func TestMiddlewareRejectsStaleAndFutureTimestamps(t *testing.T) {
	for name, offset := range map[string]int64{"stale": -301, "future": 301} {
		t.Run(name, func(t *testing.T) {
			h := newHarness(t)
			// Re-sign with the shifted timestamp so only the skew check can fail.
			rec := h.request(func(r *http.Request) {
				SignRequest(r, h.v.KeyID, []byte(h.v.Secret), []byte(h.v.Body), h.now.Add(time.Duration(offset)*time.Second), h.v.Nonce)
			})
			if rec.Code != http.StatusUnauthorized {
				t.Fatalf("status %d", rec.Code)
			}
		})
	}
	// Inside the window is accepted.
	h := newHarness(t)
	rec := h.request(func(r *http.Request) {
		SignRequest(r, h.v.KeyID, []byte(h.v.Secret), []byte(h.v.Body), h.now.Add(-299*time.Second), h.v.Nonce)
	})
	if rec.Code != http.StatusOK {
		t.Fatalf("in-window status %d", rec.Code)
	}
}

func TestMiddlewareRejectsReplayedNonce(t *testing.T) {
	h := newHarness(t)
	if rec := h.request(nil); rec.Code != http.StatusOK {
		t.Fatalf("first status %d", rec.Code)
	}
	rec := h.request(nil)
	if rec.Code != http.StatusConflict || errorCode(t, rec) != "request_replayed" {
		t.Fatalf("replay status %d body %s", rec.Code, rec.Body)
	}
}

func TestMiddlewareRejectsUnknownKey(t *testing.T) {
	h := newHarness(t)
	rec := h.request(func(r *http.Request) {
		SignRequest(r, "retired-key", []byte(h.v.Secret), []byte(h.v.Body), h.now, h.v.Nonce)
	})
	if rec.Code != http.StatusUnauthorized || errorCode(t, rec) != "unauthorized" {
		t.Fatalf("status %d body %s", rec.Code, rec.Body)
	}
}

func TestMiddlewareRejectsMissingOrMalformedHeaders(t *testing.T) {
	cases := map[string]func(*http.Request){
		"no signature":  func(r *http.Request) { r.Header.Del(HeaderSignature) },
		"no nonce":      func(r *http.Request) { r.Header.Del(HeaderNonce) },
		"short nonce":   func(r *http.Request) { r.Header.Set(HeaderNonce, "abc") },
		"iso timestamp": func(r *http.Request) { r.Header.Set(HeaderTimestamp, "2026-01-01T00:00:00Z") },
		"no version": func(r *http.Request) {
			r.Header.Set(HeaderSignature, strings.TrimPrefix(r.Header.Get(HeaderSignature), "v1="))
		},
		"v2 prefix": func(r *http.Request) {
			r.Header.Set(HeaderSignature, "v2="+strings.TrimPrefix(r.Header.Get(HeaderSignature), "v1="))
		},
		"non-hex": func(r *http.Request) { r.Header.Set(HeaderSignature, "v1="+strings.Repeat("z", 64)) },
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			if rec := newHarness(t).request(mutate); rec.Code != http.StatusUnauthorized {
				t.Fatalf("status %d", rec.Code)
			}
		})
	}
}

func TestMiddlewareRejectsOversizedBody(t *testing.T) {
	cache := NewMemoryReplayCache()
	verifier, err := NewVerifier(map[string][]byte{"k": []byte(strings.Repeat("s", 32))}, time.Minute, 8, cache)
	if err != nil {
		t.Fatal(err)
	}
	called := false
	h := verifier.Middleware(slog.New(slog.NewTextHandler(io.Discard, nil)), func(w http.ResponseWriter, _ *http.Request, status int, _, _ string) {
		w.WriteHeader(status)
	})(http.HandlerFunc(func(http.ResponseWriter, *http.Request) { called = true }))
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(http.MethodPost, "/v1/echo", strings.NewReader("0123456789")))
	if rec.Code != http.StatusRequestEntityTooLarge || called {
		t.Fatalf("status %d called %v", rec.Code, called)
	}
}

func TestSecondKeyAcceptedForRotation(t *testing.T) {
	vs := loadVectors(t)
	h := newHarness(t)
	v2 := vs[1]
	hdr := http.Header{}
	hdr.Set(HeaderKeyID, v2.KeyID)
	hdr.Set(HeaderTimestamp, v2.Timestamp)
	hdr.Set(HeaderNonce, v2.Nonce)
	hdr.Set(HeaderSignature, v2.SignatureHeader)
	keys := map[string][]byte{vs[0].KeyID: []byte(vs[0].Secret), v2.KeyID: []byte(v2.Secret)}
	verifier, _ := NewVerifier(keys, 300*time.Second, 1<<20, NewMemoryReplayCache())
	verifier.Now = func() time.Time { return h.now }
	id, err := verifier.Verify(context.Background(), v2.Method, v2.PathAndQuery, hdr, []byte(v2.Body))
	if err != nil || id != v2.KeyID {
		t.Fatalf("id %q err %v", id, err)
	}
}

func TestNewVerifierRejectsWeakKeys(t *testing.T) {
	if _, err := NewVerifier(map[string][]byte{"k": []byte("short")}, time.Minute, 1, NewMemoryReplayCache()); err == nil {
		t.Fatal("expected short secret to be rejected")
	}
	if _, err := NewVerifier(map[string][]byte{"bad id!": []byte(strings.Repeat("s", 32))}, time.Minute, 1, NewMemoryReplayCache()); err == nil {
		t.Fatal("expected bad key id to be rejected")
	}
}

func TestMemoryReplayCacheExpires(t *testing.T) {
	now := time.Unix(1767225600, 0)
	c := NewMemoryReplayCache()
	c.Now = func() time.Time { return now }
	ctx := context.Background()
	if ok, _ := c.Reserve(ctx, "a", time.Minute); !ok {
		t.Fatal("first reserve should succeed")
	}
	if ok, _ := c.Reserve(ctx, "a", time.Minute); ok {
		t.Fatal("second reserve should be a replay")
	}
	now = now.Add(2 * time.Minute)
	if ok, _ := c.Reserve(ctx, "a", time.Minute); !ok {
		t.Fatal("reserve after expiry should succeed")
	}
	if c.Len() != 1 {
		t.Fatalf("sweep should have dropped expired entries, len %d", c.Len())
	}
}
