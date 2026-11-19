// Package config loads service configuration from environment variables.
package config

import (
	"errors"
	"fmt"
	"log/slog"
	"strconv"
	"strings"
	"time"

	"github.com/kraftonnotgar-spec/Karpy-v2/services/go-template/internal/auth"
)

type Config struct {
	ServiceName     string
	Environment     string
	Port            int
	Keys            map[string][]byte
	MaxSkew         time.Duration
	MaxBodyBytes    int64
	LogLevel        slog.Level
	ShutdownTimeout time.Duration
	// OTLPEndpoint enables tracing export once an OTel SDK is wired in (see telemetry package).
	OTLPEndpoint string
	// RabbitURL selects a real broker publisher; empty means the in-memory/no-op publisher.
	RabbitURL      string
	EventsExchange string
}

// Load reads configuration through getenv (os.Getenv in production).
func Load(getenv func(string) string) (Config, error) {
	get := func(name, fallback string) string {
		if v := strings.TrimSpace(getenv(name)); v != "" {
			return v
		}
		return fallback
	}
	var errs []error
	intVar := func(name string, fallback, min, max int) int {
		raw := get(name, strconv.Itoa(fallback))
		n, err := strconv.Atoi(raw)
		if err != nil || n < min || n > max {
			errs = append(errs, fmt.Errorf("%s must be an integer from %d to %d", name, min, max))
			return fallback
		}
		return n
	}
	cfg := Config{
		ServiceName:     get("SERVICE_NAME", get("OTEL_SERVICE_NAME", "example-service")),
		Environment:     get("APP_ENV", "development"),
		Port:            intVar("PORT", 8080, 1, 65535),
		MaxSkew:         time.Duration(intVar("KARPY_SIGNATURE_MAX_SKEW_SECONDS", 300, 5, 900)) * time.Second,
		MaxBodyBytes:    int64(intVar("MAX_BODY_BYTES", 1<<20, 1024, 64<<20)),
		ShutdownTimeout: time.Duration(intVar("SHUTDOWN_TIMEOUT_SECONDS", 20, 1, 300)) * time.Second,
		OTLPEndpoint:    get("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
		RabbitURL:       get("RABBITMQ_URL", ""),
		EventsExchange:  get("RABBITMQ_EXCHANGE", "karpy.events"),
	}
	if err := cfg.LogLevel.UnmarshalText([]byte(get("LOG_LEVEL", "info"))); err != nil {
		errs = append(errs, errors.New("LOG_LEVEL must be debug, info, warn or error"))
	}
	keys, err := ParseKeys(getenv("KARPY_SERVICE_KEYS"))
	if err != nil {
		errs = append(errs, err)
	}
	cfg.Keys = keys
	return cfg, errors.Join(errs...)
}

// ParseKeys parses "keyid:secret,keyid2:secret2". There is deliberately no
// default: a service must refuse to start without keys.
func ParseKeys(raw string) (map[string][]byte, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return nil, errors.New("KARPY_SERVICE_KEYS is required (format keyid:secret[,keyid:secret])")
	}
	keys := map[string][]byte{}
	for _, item := range strings.Split(raw, ",") {
		id, secret, ok := strings.Cut(strings.TrimSpace(item), ":")
		if !ok || !auth.ValidKeyID(id) {
			return nil, fmt.Errorf("KARPY_SERVICE_KEYS: invalid key id in entry %d", len(keys)+1)
		}
		if len(secret) < auth.MinSecretBytes {
			return nil, fmt.Errorf("KARPY_SERVICE_KEYS: secret for %q must be at least %d bytes", id, auth.MinSecretBytes)
		}
		if _, dup := keys[id]; dup {
			return nil, fmt.Errorf("KARPY_SERVICE_KEYS: duplicate key id %q", id)
		}
		keys[id] = []byte(secret)
	}
	return keys, nil
}
