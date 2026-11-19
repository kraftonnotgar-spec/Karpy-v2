package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/kraftonnotgar-spec/Karpy-v2/services/go-template/internal/auth"
	"github.com/kraftonnotgar-spec/Karpy-v2/services/go-template/internal/events"
)

// Matches vector 1 in services/contracts/signing-vectors.json, which signs
// POST /v1/echo?lang=en with body {"message":"hello"}.
const (
	keyID     = "test-key-1"
	secret    = "karpy-test-secret-do-not-use-in-production-0001"
	vectorSig = "v1=52dab664eee3776e6b6a4cdf9985636a6f9b07eb68e8d54231baf005b978dec6"
	vectorTS  = 1767225600
)

func newServer(t *testing.T, checks ...Check) (*Server, http.Handler, *events.MemoryPublisher) {
	t.Helper()
	now := time.Unix(vectorTS, 0)
	verifier, err := auth.NewVerifier(map[string][]byte{keyID: []byte(secret)}, 300*time.Second, 1<<20, auth.NewMemoryReplayCache())
	if err != nil {
		t.Fatal(err)
	}
	verifier.Now = func() time.Time { return now }
	pub := &events.MemoryPublisher{}
	s := &Server{
		ServiceName: "example-service", Version: "test",
		Log:      slog.New(slog.NewTextHandler(io.Discard, nil)),
		Verifier: verifier, Publisher: pub, Checks: checks,
		Now: func() time.Time { return now },
	}
	return s, s.Handler(), pub
}

func do(h http.Handler, r *http.Request) *httptest.ResponseRecorder {
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, r)
	return rec
}

func decode(t *testing.T, rec *httptest.ResponseRecorder) map[string]any {
	t.Helper()
	var m map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &m); err != nil {
		t.Fatalf("invalid JSON %q", rec.Body.String())
	}
	return m
}

func TestHealthz(t *testing.T) {
	_, h, _ := newServer(t)
	rec := do(h, httptest.NewRequest(http.MethodGet, "/healthz", nil))
	if rec.Code != 200 || decode(t, rec)["status"] != "alive" {
		t.Fatalf("status %d body %s", rec.Code, rec.Body)
	}
}

func TestReadyzReflectsChecksAndDraining(t *testing.T) {
	s, h, _ := newServer(t, Check{Name: "postgres", Fn: func(context.Context) error { return nil }})
	if rec := do(h, httptest.NewRequest(http.MethodGet, "/readyz", nil)); rec.Code != 200 {
		t.Fatalf("ready status %d", rec.Code)
	}
	s.SetDraining()
	if rec := do(h, httptest.NewRequest(http.MethodGet, "/readyz", nil)); rec.Code != 503 {
		t.Fatalf("draining status %d", rec.Code)
	}
	_, h2, _ := newServer(t, Check{Name: "broker", Fn: func(context.Context) error { return errors.New("down") }})
	rec := do(h2, httptest.NewRequest(http.MethodGet, "/readyz", nil))
	checks, _ := decode(t, rec)["checks"].(map[string]any)
	if rec.Code != 503 || checks["broker"] != "unavailable" {
		t.Fatalf("status %d body %s", rec.Code, rec.Body)
	}
}

func signedEcho() *http.Request {
	r := httptest.NewRequest(http.MethodPost, "/v1/echo?lang=en", strings.NewReader(`{"message":"hello"}`))
	r.Header.Set(auth.HeaderKeyID, keyID)
	r.Header.Set(auth.HeaderTimestamp, "1767225600")
	r.Header.Set(auth.HeaderNonce, "4f1c2a9e8b7d6c5f4e3d2c1b0a998877")
	r.Header.Set(auth.HeaderSignature, vectorSig)
	r.Header.Set(HeaderRequestID, "req-test-1")
	r.Header.Set("traceparent", "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01")
	return r
}

func TestSignedEchoEndToEnd(t *testing.T) {
	_, h, pub := newServer(t)
	rec := do(h, signedEcho())
	if rec.Code != 200 {
		t.Fatalf("status %d body %s", rec.Code, rec.Body)
	}
	body := decode(t, rec)
	if body["message"] != "hello" || body["key_id"] != keyID || body["request_id"] != "req-test-1" || rec.Header().Get(HeaderRequestID) != "req-test-1" {
		t.Fatalf("unexpected body %v", body)
	}
	evts := pub.Events()
	if len(evts) != 1 || evts[0].Type != "example.echo.received" || evts[0].CorrelationID != "req-test-1" ||
		!strings.HasPrefix(evts[0].Traceparent, "00-4bf92f3577b34da6a3ce929d0e0e4736-") {
		t.Fatalf("unexpected events %+v", evts)
	}
}

func TestErrorShape(t *testing.T) {
	_, h, _ := newServer(t)
	r := signedEcho()
	r.Header.Set(auth.HeaderSignature, "v1="+strings.Repeat("a", 64))
	rec := do(h, r)
	errObj, _ := decode(t, rec)["error"].(map[string]any)
	if rec.Code != 401 || errObj["code"] != "unauthorized" || errObj["request_id"] != "req-test-1" || errObj["message"] == "" {
		t.Fatalf("status %d body %s", rec.Code, rec.Body)
	}
	rec = do(h, httptest.NewRequest(http.MethodGet, "/nope", nil))
	errObj, _ = decode(t, rec)["error"].(map[string]any)
	if rec.Code != 404 || errObj["code"] != "not_found" || errObj["request_id"] == "" {
		t.Fatalf("status %d body %s", rec.Code, rec.Body)
	}
}

func TestEchoValidatesBodyAfterAuth(t *testing.T) {
	_, h, _ := newServer(t)
	now := time.Unix(vectorTS, 0)
	r := httptest.NewRequest(http.MethodPost, "/v1/echo", strings.NewReader(`{"message":""}`))
	auth.SignRequest(r, keyID, []byte(secret), []byte(`{"message":""}`), now, "nonce-validation-000001")
	rec := do(h, r)
	errObj, _ := decode(t, rec)["error"].(map[string]any)
	if rec.Code != 400 || errObj["code"] != "invalid_request" {
		t.Fatalf("status %d body %s", rec.Code, rec.Body)
	}
}
