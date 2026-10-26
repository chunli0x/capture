USDC liveness port, 2026-10-26

This build mirrors Clock In commit `e8b8845` ("Fix liveness entry,
completion recovery, and camera lifecycle"). The USDC checkout also lacked
the earlier liveness intro and demo entry point, so the port includes the
source screen's artwork, two supporting icons, and optional button label style.

- The human-check gate sits immediately below the judge heading, independent
  of whether a judgment pair is loaded.
- Begin check and Continue (demo) appear above the intro artwork. Only Begin
  requests camera permission; demo submits the same nonzero 32-byte digest
  as Clock In, without requiring camera permission.
- Session creation errors remain visible with retry, cancel, and back actions,
  including before a challenge exists. Starting a session clears stale state.
- Completion waits for server acceptance. Failures keep liveness open with a
  fresh-session retry; submissions are disabled while a request is busy.
  Successful completion sets the local flag before refreshing judgment data,
  so a later refresh failure cannot strand the consumed session.
- Spoof crops rotate sensor bitmaps into ML Kit's face-coordinate system.
  Leaving the screen clears analysis and unbinds its camera use cases;
  callbacks after disposal are ignored, and camera startup errors are shown.

USDC identifiers, wire fields, and product strings are retained. Backend
production behavior is unchanged. Ported API regressions cover the exact demo
digest and a motion-style digest, persistent completion, judging access,
wallet isolation, replay rejection, invalid-result retry, and session expiry
and replacement.

Validation in this checkout:

- From `backend/`: `SEEKER_LOCAL_SQLITE=true /home/hermes/tap-ci/backend/.venv/bin/python -m pytest -q`
  — 60 passed, 8 skipped. The skips require the absent
  `target/deploy/seeker_bounty.so` artifact.
- From `android/`: `ANDROID_HOME=/home/hermes/android-sdk ./gradlew testDebugUnitTest lintDebug --console=plain`
  — build successful; 64 unit tests passed with no failures, errors, or skips;
  lint completed successfully.
- The liveness screen, supporting icon/button changes, and artwork match
  `e8b8845` exactly. All added liveness hunks are present, and no SKR
  identifiers or strings were added to application or test code.

Device smoke checks remain necessary for camera inference and permission UI:
verify the gate on an unverified account; use demo with camera permission
denied; run Begin check; cancel and reenter; expire a session and retry; and
disconnect networking to exercise session-start and completion recovery.
