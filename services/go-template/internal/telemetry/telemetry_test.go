package telemetry

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestMiddlewareContinuesValidTraceAndStartsNewOtherwise(t *testing.T) {
	var got TraceContext
	h := Middleware(http.HandlerFunc(func(_ http.ResponseWriter, r *http.Request) { got = FromContext(r.Context()) }))

	r := httptest.NewRequest(http.MethodGet, "/", nil)
	r.Header.Set("traceparent", "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01")
	h.ServeHTTP(httptest.NewRecorder(), r)
	if got.TraceID != "4bf92f3577b34da6a3ce929d0e0e4736" || got.SpanID == "00f067aa0ba902b7" || len(got.SpanID) != 16 {
		t.Fatalf("trace not continued: %+v", got)
	}

	for _, bad := range []string{"", "garbage", "00-00000000000000000000000000000000-00f067aa0ba902b7-01", "ff-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"} {
		r = httptest.NewRequest(http.MethodGet, "/", nil)
		r.Header.Set("traceparent", bad)
		h.ServeHTTP(httptest.NewRecorder(), r)
		if len(got.TraceID) != 32 || got.TraceID == "4bf92f3577b34da6a3ce929d0e0e4736" {
			t.Fatalf("expected a new trace for %q, got %+v", bad, got)
		}
	}
}
