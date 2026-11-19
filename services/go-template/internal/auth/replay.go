package auth

import (
	"context"
	"sync"
	"time"
)

// ReplayCache remembers nonces for at least the signature validity window.
//
// MemoryReplayCache is correct only for a single replica. With more than one
// replica, implement this interface on a shared store, e.g. Redis:
//
//	SET karpy:nonce:<key>  1  NX  EX <ttl seconds>   // OK => fresh, nil => replay
type ReplayCache interface {
	// Reserve stores key for ttl and returns true, or returns false if the key
	// is already stored and not yet expired.
	Reserve(ctx context.Context, key string, ttl time.Duration) (bool, error)
}

// MemoryReplayCache is an in-process ReplayCache with lazy expiry.
type MemoryReplayCache struct {
	mu        sync.Mutex
	entries   map[string]time.Time
	lastSweep time.Time
	// Now is the clock; replaceable in tests.
	Now func() time.Time
}

func NewMemoryReplayCache() *MemoryReplayCache {
	return &MemoryReplayCache{entries: map[string]time.Time{}, Now: time.Now}
}

func (c *MemoryReplayCache) Reserve(_ context.Context, key string, ttl time.Duration) (bool, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	now := c.Now()
	if now.Sub(c.lastSweep) > time.Minute {
		for k, exp := range c.entries {
			if !now.Before(exp) {
				delete(c.entries, k)
			}
		}
		c.lastSweep = now
	}
	if exp, ok := c.entries[key]; ok && now.Before(exp) {
		return false, nil
	}
	c.entries[key] = now.Add(ttl)
	return true, nil
}

// Len returns the number of stored entries (for tests and metrics).
func (c *MemoryReplayCache) Len() int {
	c.mu.Lock()
	defer c.mu.Unlock()
	return len(c.entries)
}
