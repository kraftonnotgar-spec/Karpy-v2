// Command server runs the example Karpy service.
package main

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"syscall"
	"time"

	"github.com/kraftonnotgar-spec/Karpy-v2/services/go-template/internal/auth"
	"github.com/kraftonnotgar-spec/Karpy-v2/services/go-template/internal/config"
	"github.com/kraftonnotgar-spec/Karpy-v2/services/go-template/internal/events"
	"github.com/kraftonnotgar-spec/Karpy-v2/services/go-template/internal/httpapi"
	"github.com/kraftonnotgar-spec/Karpy-v2/services/go-template/internal/telemetry"
)

// version is set at build time: -ldflags "-X main.version=1.2.3".
var version = "dev"

func main() {
	// Distroless images have no shell or curl: the binary probes itself.
	if len(os.Args) > 1 && (os.Args[1] == "--healthcheck" || os.Args[1] == "--readycheck") {
		os.Exit(probe(os.Args[1]))
	}
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "fatal:", err)
		os.Exit(1)
	}
}

func probe(flag string) int {
	path := "/healthz"
	if flag == "--readycheck" {
		path = "/readyz"
	}
	port := os.Getenv("PORT")
	if _, err := strconv.Atoi(port); err != nil {
		port = "8080"
	}
	client := http.Client{Timeout: 2 * time.Second}
	resp, err := client.Get("http://127.0.0.1:" + port + path)
	if err != nil {
		return 1
	}
	_ = resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return 1
	}
	return 0
}

func run() error {
	cfg, err := config.Load(os.Getenv)
	if err != nil {
		return err
	}
	log := slog.New(telemetry.ContextHandler{Handler: slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: cfg.LogLevel})}).
		With("service", cfg.ServiceName, "environment", cfg.Environment, "version", version)
	slog.SetDefault(log)

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	shutdownTelemetry := telemetry.Init(ctx, cfg.OTLPEndpoint, cfg.ServiceName, log)

	verifier, err := auth.NewVerifier(cfg.Keys, cfg.MaxSkew, cfg.MaxBodyBytes, auth.NewMemoryReplayCache())
	if err != nil {
		return err
	}

	var publisher events.Publisher = events.NoopPublisher{}
	if cfg.RabbitURL != "" {
		// Seam: replace with an amqp091-go publisher (confirms + mandatory) fed by an outbox relay.
		log.Warn("RABBITMQ_URL is set but this template ships no broker client; events are dropped", "exchange", cfg.EventsExchange)
	}

	server := &httpapi.Server{
		ServiceName: cfg.ServiceName,
		Version:     version,
		Log:         log,
		Verifier:    verifier,
		Publisher:   publisher,
		// Add one Check per hard dependency, e.g. {Name: "postgres", Fn: pool.Ping}.
		Checks: nil,
	}
	httpServer := &http.Server{
		Addr:              ":" + strconv.Itoa(cfg.Port),
		Handler:           server.Handler(),
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       30 * time.Second,
		WriteTimeout:      30 * time.Second,
		IdleTimeout:       90 * time.Second,
		MaxHeaderBytes:    32 << 10,
	}

	errCh := make(chan error, 1)
	go func() {
		log.Info("listening", "port", cfg.Port, "keys", len(cfg.Keys))
		errCh <- httpServer.ListenAndServe()
	}()

	select {
	case err := <-errCh:
		if !errors.Is(err, http.ErrServerClosed) {
			return err
		}
	case <-ctx.Done():
	}

	log.Info("shutting down")
	server.SetDraining()
	shutdownCtx, cancel := context.WithTimeout(context.Background(), cfg.ShutdownTimeout)
	defer cancel()
	if err := httpServer.Shutdown(shutdownCtx); err != nil {
		log.Error("graceful shutdown incomplete", "error", err)
	}
	if err := shutdownTelemetry(shutdownCtx); err != nil {
		log.Warn("telemetry shutdown failed", "error", err)
	}
	return nil
}
