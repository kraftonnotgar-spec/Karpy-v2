// Package httpapi wires routes, the JSON error shape, request ids and request
// logging for the service.
package httpapi

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"regexp"
	"sync"
	"sync/atomic"
	"time"

	"github.com/kraftonnotgar-spec/Karpy-v2/services/go-template/internal/auth"
	"github.com/kraftonnotgar-spec/Karpy-v2/services/go-template/internal/events"
	"github.com/kraftonnotgar-spec/Karpy-v2/services/go-template/internal/telemetry"
)

const HeaderRequestID = "X-Request-Id"

var requestIDPattern = regexp.MustCompile(`^[A-Za-z0-9._:-]{1,128}$`)

// Check is one readiness dependency (database, broker, cache...).
type Check struct {
	Name string
	Fn   func(context.Context) error
}

type Server struct {
	ServiceName string
	Version     string
	Log         *slog.Logger
	Verifier    *auth.Verifier
	Publisher   events.Publisher
	Checks      []Check
	Now         func() time.Time

	draining atomic.Bool
}

// SetDraining makes /readyz fail so load balancers stop routing new traffic
// before shutdown completes.
func (s *Server) SetDraining() { s.draining.Store(true) }

func (s *Server) Handler() http.Handler {
	if s.Now == nil {
		s.Now = time.Now
	}
	signed := s.Verifier.Middleware(s.Log, WriteError)
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", s.healthz)
	mux.HandleFunc("GET /readyz", s.readyz)
	mux.Handle("POST /v1/echo", signed(http.HandlerFunc(s.echo)))
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		WriteError(w, r, http.StatusNotFound, "not_found", "Route not found.")
	})
	return telemetry.Middleware(s.requestContext(mux))
}

// ---- error shape -----------------------------------------------------------

type ctxKey struct{}

// RequestID returns the request id for the current request.
func RequestID(ctx context.Context) string {
	id, _ := ctx.Value(ctxKey{}).(string)
	return id
}

// WriteError writes {"error":{"code","message","request_id"}}.
func WriteError(w http.ResponseWriter, r *http.Request, status int, code, message string) {
	writeJSON(w, status, map[string]any{"error": map[string]string{
		"code": code, "message": message, "request_id": RequestID(r.Context()),
	}})
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

// ---- request id + access log ---------------------------------------------------

type statusRecorder struct {
	http.ResponseWriter
	status int
}

func (r *statusRecorder) WriteHeader(code int) { r.status = code; r.ResponseWriter.WriteHeader(code) }

func (s *Server) requestContext(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		id := r.Header.Get(HeaderRequestID)
		if !requestIDPattern.MatchString(id) {
			b := make([]byte, 16)
			_, _ = rand.Read(b)
			id = hex.EncodeToString(b)
		}
		w.Header().Set(HeaderRequestID, id)
		ctx := context.WithValue(r.Context(), ctxKey{}, id)
		rec := &statusRecorder{ResponseWriter: w, status: http.StatusOK}
		start := time.Now()
		r = r.WithContext(ctx)
		next.ServeHTTP(rec, r)
		route := r.Pattern
		if route == "" {
			route = "unmatched"
		}
		level := slog.LevelInfo
		if r.URL.Path == "/healthz" || r.URL.Path == "/readyz" {
			level = slog.LevelDebug
		}
		s.Log.Log(ctx, level, "http request", "method", r.Method, "route", route, "status", rec.status,
			"duration_ms", time.Since(start).Milliseconds(), "request_id", id)
	})
}

// ---- ops endpoints -------------------------------------------------------------

func (s *Server) healthz(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"status": "alive", "service": s.ServiceName, "version": s.Version})
}

func (s *Server) readyz(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	checks := make(map[string]string, len(s.Checks)+1)
	ready := !s.draining.Load()
	if !ready {
		checks["draining"] = "unavailable"
	}
	var mu sync.Mutex
	var wg sync.WaitGroup
	for _, c := range s.Checks {
		wg.Add(1)
		go func() {
			defer wg.Done()
			err := c.Fn(ctx)
			mu.Lock()
			defer mu.Unlock()
			if err != nil {
				ready = false
				checks[c.Name] = "unavailable"
				s.Log.WarnContext(r.Context(), "readiness check failed", "check", c.Name, "error", err)
				return
			}
			checks[c.Name] = "ready"
		}()
	}
	wg.Wait()
	if !ready {
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{"status": "unavailable", "checks": checks})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"status": "ready", "checks": checks})
}

// ---- example signed endpoint ---------------------------------------------------

type echoRequest struct {
	Message string `json:"message"`
}

func (s *Server) echo(w http.ResponseWriter, r *http.Request) {
	var in echoRequest
	dec := json.NewDecoder(r.Body)
	dec.DisallowUnknownFields()
	if err := dec.Decode(&in); err != nil || dec.More() {
		WriteError(w, r, http.StatusBadRequest, "invalid_request", "Body must be a JSON object with a message.")
		return
	}
	if in.Message == "" || len(in.Message) > 1024 {
		WriteError(w, r, http.StatusBadRequest, "invalid_request", "message must be 1 to 1024 characters.")
		return
	}
	ctx := r.Context()
	now := s.Now().UTC()
	requestID := RequestID(ctx)
	// With a database, insert this envelope into the outbox in the same
	// transaction as the state change instead (see package events).
	event, err := events.New(s.ServiceName, "example.echo.received", 1, map[string]string{"message": in.Message},
		events.Meta{CorrelationID: requestID, CausationID: requestID, Traceparent: telemetry.FromContext(ctx).Traceparent()}, now)
	if err == nil {
		err = s.Publisher.Publish(ctx, event)
	}
	if err != nil {
		s.Log.ErrorContext(ctx, "event publish failed", "error", errors.Unwrap(err))
		WriteError(w, r, http.StatusInternalServerError, "internal_error", "The request could not be completed.")
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{
		"message": in.Message, "key_id": auth.KeyIDFromContext(ctx), "request_id": requestID,
		"received_at": now.Format(time.RFC3339),
	})
}
