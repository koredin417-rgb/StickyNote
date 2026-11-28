# Phase 11, calm rail: decisions so far (2026-11-28)

- The rail shows while the note has the keyboard focus **or** the pointer is over it, and hides
  only when neither is true (the user's call: focus loss alone would not cover the mouse leaving).
- It comes back with a quick fade (about 120 ms, `anim.FAST`); Reduced keeps the fade, Off is instant.
- Still to settle when the phase starts: how it hides (fade or slide), what takes its space (the
  text widens or the rail's room stays), and keyboard-only use.
