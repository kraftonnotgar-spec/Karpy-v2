package events

import (
	"context"
	"encoding/json"
	"regexp"
	"testing"
	"time"
)

var uuidV7 = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`)

func TestNewEnvelope(t *testing.T) {
	now := time.Unix(1767225600, 0)
	e, err := New("example-service", "example.echo.received", 1, map[string]string{"message": "hi"}, Meta{CorrelationID: "req-1"}, now)
	if err != nil {
		t.Fatal(err)
	}
	if !uuidV7.MatchString(e.ID) || e.IdempotencyKey != e.ID || e.CorrelationID != "req-1" {
		t.Fatalf("unexpected envelope %+v", e)
	}
	raw, _ := json.Marshal(e)
	var decoded map[string]any
	_ = json.Unmarshal(raw, &decoded)
	for _, field := range []string{"id", "type", "version", "source", "occurred_at", "idempotency_key", "data"} {
		if _, ok := decoded[field]; !ok {
			t.Errorf("missing required field %s in %s", field, raw)
		}
	}
	if decoded["occurred_at"] != "2026-01-01T00:00:00Z" {
		t.Errorf("occurred_at %v", decoded["occurred_at"])
	}
}

func TestNewEnvelopeRejectsBadType(t *testing.T) {
	for _, typ := range []string{"echo", "Example.echo.received", "a.b", "a.b.c.d"} {
		if _, err := New("s", typ, 1, map[string]string{}, Meta{}, time.Now()); err == nil {
			t.Errorf("expected error for %q", typ)
		}
	}
}

func TestMemoryPublisher(t *testing.T) {
	p := &MemoryPublisher{}
	e, _ := New("s", "a.b.c", 1, map[string]string{}, Meta{}, time.Now())
	_ = p.Publish(context.Background(), e)
	if got := p.Events(); len(got) != 1 || got[0].ID != e.ID {
		t.Fatalf("got %+v", got)
	}
}
