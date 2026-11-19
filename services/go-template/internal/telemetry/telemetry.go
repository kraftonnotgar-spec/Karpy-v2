// Package telemetry is the observability seam of the template. It is
// stdlib-only: it accepts and propagates W3C trace context and puts trace ids
// on every log line, so logs correlate with KARPy and other services even
// before an OpenTelemetry SDK is linked.
//
// To export traces/metrics/logs over OTLP, add go.opentelemetry.io/otel,
// .../sdk and .../exporters/otlp/otlptrace/otlptracegrpc (plus otelhttp), then
// in Init: build a TracerProvider with a batch OTLP exporter pointed at
// OTEL_EXPORTER_OTLP_ENDPOINT, set the TraceContext+Baggage propagator, wrap
// the HTTP handler with otelhttp.NewHandler, and have TraceFields read the
// span context instead of the parsed header. Nothing else needs to change.
package telemetry

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"log/slog"
	"net/http"
	"regexp"
)

var traceparentPattern = regexp.MustCompile(`^([0-9a-f]{2})-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$`)

// TraceContext is the W3C trace context of the current request.
type TraceContext struct {
	TraceID string
	SpanID  string // this service's span id for the request
	Flags   string
}

// Traceparent renders the header to send on outbound calls/events.
func (t TraceContext) Traceparent() string {
	if t.TraceID == "" {
		return ""
	}
	return "00-" + t.TraceID + "-" + t.SpanID + "-" + t.Flags
}

type ctxKey struct{}

// FromContext returns the trace context stored by Middleware.
func FromContext(ctx context.Context) TraceContext {
	tc, _ := ctx.Value(ctxKey{}).(TraceContext)
	return tc
}

// TraceFields returns slog attributes for the request's trace.
func TraceFields(ctx context.Context) []any {
	tc := FromContext(ctx)
	if tc.TraceID == "" {
		return nil
	}
	return []any{"trace_id", tc.TraceID, "span_id", tc.SpanID}
}

func randomHex(n int) string {
	b := make([]byte, n)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

// Parse validates a traceparent header (version 00, non-zero ids).
func Parse(header string) (traceID, parentID, flags string, ok bool) {
	m := traceparentPattern.FindStringSubmatch(header)
	if m == nil || m[1] == "ff" || m[2] == "00000000000000000000000000000000" || m[3] == "0000000000000000" {
		return "", "", "", false
	}
	return m[2], m[3], m[4], true
}

// Middleware continues the caller's trace (or starts one) and stores it in the
// request context. It does not export spans; see the package comment.
func Middleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		traceID, _, flags, ok := Parse(r.Header.Get("traceparent"))
		if !ok {
			traceID, flags = randomHex(16), "01"
		}
		tc := TraceContext{TraceID: traceID, SpanID: randomHex(8), Flags: flags}
		next.ServeHTTP(w, r.WithContext(context.WithValue(r.Context(), ctxKey{}, tc)))
	})
}

// Init is where an OTel SDK would be started. It returns a shutdown func.
func Init(_ context.Context, endpoint, service string, log *slog.Logger) func(context.Context) error {
	if endpoint != "" {
		log.Info("OTLP endpoint configured but no OpenTelemetry SDK is linked in this template; traces are propagated, not exported",
			"endpoint", endpoint, "service", service)
	}
	return func(context.Context) error { return nil }
}

// ContextHandler is a slog.Handler that adds trace ids from the context to
// every record logged with a *Context method.
type ContextHandler struct{ slog.Handler }

func (h ContextHandler) Handle(ctx context.Context, rec slog.Record) error {
	if fields := TraceFields(ctx); fields != nil {
		rec.Add(fields...)
	}
	return h.Handler.Handle(ctx, rec)
}

func (h ContextHandler) WithAttrs(attrs []slog.Attr) slog.Handler {
	return ContextHandler{h.Handler.WithAttrs(attrs)}
}

func (h ContextHandler) WithGroup(name string) slog.Handler {
	return ContextHandler{h.Handler.WithGroup(name)}
}
