package config

import (
	"strings"
	"testing"
	"time"
)

func env(values map[string]string) func(string) string {
	return func(k string) string { return values[k] }
}

var secret = strings.Repeat("x", 32)

func TestLoadDefaultsAndKeys(t *testing.T) {
	cfg, err := Load(env(map[string]string{"KARPY_SERVICE_KEYS": "k1:" + secret + ", k2:" + secret + "y"}))
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Port != 8080 || cfg.MaxSkew != 300*time.Second || cfg.EventsExchange != "karpy.events" || len(cfg.Keys) != 2 {
		t.Fatalf("unexpected config %+v", cfg)
	}
	if string(cfg.Keys["k2"]) != secret+"y" {
		t.Fatal("secret not parsed")
	}
}

func TestLoadRequiresKeys(t *testing.T) {
	if _, err := Load(env(nil)); err == nil || !strings.Contains(err.Error(), "KARPY_SERVICE_KEYS") {
		t.Fatalf("expected missing keys error, got %v", err)
	}
}

func TestParseKeysRejectsBadInput(t *testing.T) {
	for _, raw := range []string{"nocolon", "k:short", ":" + secret, "bad id:" + secret, "k:" + secret + ",k:" + secret} {
		if _, err := ParseKeys(raw); err == nil {
			t.Errorf("expected error for %q", raw)
		}
	}
	// Secrets may contain ':'.
	if keys, err := ParseKeys("k:" + secret + ":tail"); err != nil || string(keys["k"]) != secret+":tail" {
		t.Fatalf("keys %v err %v", keys, err)
	}
}

func TestLoadRejectsBadNumbers(t *testing.T) {
	if _, err := Load(env(map[string]string{"KARPY_SERVICE_KEYS": "k:" + secret, "PORT": "http"})); err == nil {
		t.Fatal("expected PORT error")
	}
}
