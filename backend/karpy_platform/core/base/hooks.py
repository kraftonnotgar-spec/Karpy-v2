"""
KARPy CMS — Hook System (like Botble's add_filter / add_action / do_action).

This is the heart of the plugin communication system. Plugins use hooks
to modify data (filters) or react to events (actions) without touching
core code. This is exactly how WordPress and Botble work internally.

Usage:
    from karpy_platform.core.base.hooks import hooks

    # Register a filter (modifies data)
    hooks.add_filter('page_content', my_shortcode_processor, priority=10)

    # Apply a filter (run all registered processors)
    content = hooks.apply_filters('page_content', raw_html)

    # Register an action (reacts to events)
    hooks.add_action('plugin_activated', send_notification, priority=5)

    # Fire an action
    hooks.do_action('plugin_activated', plugin_name)
"""

from typing import Any, Callable
from collections import defaultdict
import asyncio
import inspect


class HookSystem:
    """
    A priority-based hook system ported from Botble/WordPress PHP patterns.
    Supports both sync and async callbacks.
    """

    def __init__(self):
        self._filters: dict[str, list[tuple[int, Callable]]] = defaultdict(list)
        self._actions: dict[str, list[tuple[int, Callable]]] = defaultdict(list)

    # ─── Filters (modify and return data) ─────────────────────────

    def add_filter(self, hook_name: str, callback: Callable, priority: int = 10):
        """Register a filter callback. Lower priority = runs first."""
        self._filters[hook_name].append((priority, callback))
        self._filters[hook_name].sort(key=lambda x: x[0])

    def apply_filters(self, hook_name: str, value: Any, *args, **kwargs) -> Any:
        """Run all registered filters on a value and return the modified result."""
        if hook_name not in self._filters:
            return value

        for priority, callback in self._filters[hook_name]:
            if inspect.iscoroutinefunction(callback):
                try:
                    asyncio.get_running_loop()
                except RuntimeError:
                    value = asyncio.run(callback(value, *args, **kwargs))
                else:
                    raise RuntimeError(
                        f"Cannot run async filter '{hook_name}' in a running event loop; use apply_filters_async()."
                    )
            else:
                value = callback(value, *args, **kwargs)

        return value

    async def apply_filters_async(self, hook_name: str, value: Any, *args, **kwargs) -> Any:
        """Async version — awaits async callbacks properly."""
        if hook_name not in self._filters:
            return value

        for priority, callback in self._filters[hook_name]:
            if inspect.iscoroutinefunction(callback):
                value = await callback(value, *args, **kwargs)
            else:
                value = callback(value, *args, **kwargs)

        return value

    def remove_filter(self, hook_name: str, callback: Callable):
        """Remove a specific filter callback."""
        if hook_name in self._filters:
            self._filters[hook_name] = [
                (p, cb) for p, cb in self._filters[hook_name] if cb != callback
            ]

    # ─── Actions (fire-and-forget events) ─────────────────────────

    def add_action(self, hook_name: str, callback: Callable, priority: int = 10):
        """Register an action callback. Lower priority = runs first."""
        self._actions[hook_name].append((priority, callback))
        self._actions[hook_name].sort(key=lambda x: x[0])

    def do_action(self, hook_name: str, *args, **kwargs):
        """Fire all registered actions for a hook (sync version)."""
        if hook_name not in self._actions:
            return

        for priority, callback in self._actions[hook_name]:
            if inspect.iscoroutinefunction(callback):
                try:
                    asyncio.get_running_loop()
                except RuntimeError:
                    asyncio.run(callback(*args, **kwargs))
                else:
                    raise RuntimeError(
                        f"Cannot run async action '{hook_name}' in a running event loop; use do_action_async()."
                    )
            else:
                callback(*args, **kwargs)

    async def do_action_async(self, hook_name: str, *args, **kwargs):
        """Fire all registered actions for a hook (async version)."""
        if hook_name not in self._actions:
            return

        for priority, callback in self._actions[hook_name]:
            if inspect.iscoroutinefunction(callback):
                await callback(*args, **kwargs)
            else:
                callback(*args, **kwargs)

    def remove_action(self, hook_name: str, callback: Callable):
        """Remove a specific action callback."""
        if hook_name in self._actions:
            self._actions[hook_name] = [
                (p, cb) for p, cb in self._actions[hook_name] if cb != callback
            ]

    # ─── Introspection ────────────────────────────────────────────

    def get_registered_filters(self, hook_name: str = None) -> dict:
        if hook_name:
            return {hook_name: self._filters.get(hook_name, [])}
        return dict(self._filters)

    def get_registered_actions(self, hook_name: str = None) -> dict:
        if hook_name:
            return {hook_name: self._actions.get(hook_name, [])}
        return dict(self._actions)

    def has_filter(self, hook_name: str) -> bool:
        return hook_name in self._filters and len(self._filters[hook_name]) > 0

    def has_action(self, hook_name: str) -> bool:
        return hook_name in self._actions and len(self._actions[hook_name]) > 0


# Global singleton — all plugins share this instance
hooks = HookSystem()
