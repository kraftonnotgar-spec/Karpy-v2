// Package events defines the Karpy event envelope
// (services/contracts/event-envelope.schema.json) and a Publisher seam.
//
// # Outbox
//
// A service that owns a database must not publish directly from a request
// handler: the state change can commit while the publish fails (or the
// reverse). Instead, in the same database transaction as the state change,
// INSERT the marshalled Envelope into an outbox table:
//
//	CREATE TABLE event_outbox (
//	  id            uuid PRIMARY KEY,          -- Envelope.ID
//	  type          text NOT NULL,             -- routing key
//	  payload       jsonb NOT NULL,            -- full envelope
//	  status        text NOT NULL DEFAULT 'pending', -- pending|published|dead
//	  attempts      int  NOT NULL DEFAULT 0,
//	  available_at  timestamptz NOT NULL DEFAULT now(),
//	  created_at    timestamptz NOT NULL DEFAULT now(),
//	  published_at  timestamptz,
//	  last_error    text
//	);
//
// A relay loop claims pending rows (SELECT ... FOR UPDATE SKIP LOCKED LIMIT n),
// publishes each with publisher confirms and mandatory=true, marks it
// published, and on failure backs off exponentially (available_at) until a max
// attempt count, after which it marks it dead and alerts. Delivery is
// at-least-once, so consumers dedupe on idempotency_key (inbox table).
//
// The template has no database, so the example handler calls Publisher
// directly; replace that call with an outbox insert when you add storage.
package events

import (
	"context"
	"crypto/rand"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"fmt"
	"regexp"
	"sync"
	"time"
)

var typePattern = regexp.MustCompile(`^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$`)

// Envelope is the wire shape of every event. The routing key is Type.
type Envelope struct {
	ID             string    `json:"id"`
	Type           string    `json:"type"`
	Version        int       `json:"version"`
	Source         string    `json:"source"`
	OccurredAt     time.Time `json:"occurred_at"`
	CorrelationID  string    `json:"correlation_id,omitempty"`
	CausationID    string    `json:"causation_id,omitempty"`
	IdempotencyKey string    `json:"idempotency_key"`
	Traceparent    string    `json:"traceparent,omitempty"`
	Data           any       `json:"data"`
}

// Meta carries the optional linking fields of an envelope.
type Meta struct {
	CorrelationID  string
	CausationID    string
	IdempotencyKey string // defaults to the event id
	Traceparent    string
}

// New builds a validated envelope with a fresh UUIDv7 id.
func New(source, eventType string, version int, data any, meta Meta, now time.Time) (Envelope, error) {
	if !typePattern.MatchString(eventType) || len(eventType) > 128 {
		return Envelope{}, fmt.Errorf("event type %q must be <domain>.<entity>.<event>", eventType)
	}
	if version < 1 || source == "" || data == nil {
		return Envelope{}, errors.New("event requires version >= 1, a source and data")
	}
	id, err := NewUUIDv7(now)
	if err != nil {
		return Envelope{}, err
	}
	key := meta.IdempotencyKey
	if key == "" {
		key = id
	}
	return Envelope{
		ID: id, Type: eventType, Version: version, Source: source, OccurredAt: now.UTC(),
		CorrelationID: meta.CorrelationID, CausationID: meta.CausationID, IdempotencyKey: key,
		Traceparent: meta.Traceparent, Data: data,
	}, nil
}

// NewUUIDv7 returns an RFC 9562 version 7 UUID (time-ordered).
func NewUUIDv7(now time.Time) (string, error) {
	var b [16]byte
	if _, err := rand.Read(b[6:]); err != nil {
		return "", err
	}
	var ms [8]byte
	binary.BigEndian.PutUint64(ms[:], uint64(now.UnixMilli()))
	copy(b[0:6], ms[2:8])
	b[6] = (b[6] & 0x0f) | 0x70 // version 7
	b[8] = (b[8] & 0x3f) | 0x80 // RFC 4122 variant
	h := hex.EncodeToString(b[:])
	return h[0:8] + "-" + h[8:12] + "-" + h[12:16] + "-" + h[16:20] + "-" + h[20:32], nil
}

// Publisher sends envelopes to the events exchange. A RabbitMQ implementation
// (github.com/rabbitmq/amqp091-go) should: declare a durable topic exchange,
// enable publisher confirms, publish with mandatory=true, DeliveryMode
// persistent, ContentType application/json, MessageId = Envelope.ID, routing
// key = Envelope.Type, and copy traceparent into the AMQP headers.
type Publisher interface {
	Publish(ctx context.Context, e Envelope) error
}

// NoopPublisher drops events (used when RABBITMQ_URL is not set).
type NoopPublisher struct{}

func (NoopPublisher) Publish(context.Context, Envelope) error { return nil }

// MemoryPublisher records events in memory (tests and local development).
type MemoryPublisher struct {
	mu     sync.Mutex
	events []Envelope
}

func (p *MemoryPublisher) Publish(_ context.Context, e Envelope) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.events = append(p.events, e)
	return nil
}

// Events returns a copy of the recorded events.
func (p *MemoryPublisher) Events() []Envelope {
	p.mu.Lock()
	defer p.mu.Unlock()
	return append([]Envelope(nil), p.events...)
}
