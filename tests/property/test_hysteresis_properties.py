"""Property-based tests para HysteresisFilter — Bloqueo de conmutaciones automáticas dentro del cooldown.

**Validates: Requirements 8.2, 8.4**
"""

from __future__ import annotations

from hypothesis import given, settings, assume, note
from hypothesis.strategies import (
    integers,
    lists,
    sampled_from,
    composite,
    just,
)

from switch_bot.engines.hysteresis_filter import HysteresisFilter
from switch_bot.models.enums import SourceOrigin
from switch_bot.models.inference import CameraDecision


# --- Strategies ---

valid_cooldown_frames = integers(min_value=1, max_value=300)
valid_target_cam = integers(min_value=1, max_value=4)


@composite
def auto_camera_decision(draw):
    """Genera una CameraDecision con origen AUTO."""
    cam = draw(valid_target_cam)
    return CameraDecision(
        target_cam=cam,
        reason="auto decision",
        source_origin=SourceOrigin.AUTO,
    )


@composite
def sequence_of_auto_decisions(draw, min_size: int = 2, max_size: int = 20):
    """Genera una secuencia de CameraDecisions automáticas."""
    decisions = draw(
        lists(auto_camera_decision(), min_size=min_size, max_size=max_size)
    )
    return decisions


class TestProperty3HysteresisBlocksAutomaticSwitches:
    """Property 3: El filtro de histéresis bloquea conmutaciones automáticas dentro del cooldown.

    **Validates: Requirements 8.2, 8.4**

    Para cualquier secuencia de CameraDecisions automáticas, el HysteresisFilter
    debe rechazar todos los switches que ocurran dentro de los `cooldown_frames`
    posteriores al último switch aprobado. Mientras el cooldown está activo,
    la escena actual se mantiene sin cambios.
    """

    @given(
        cooldown_frames=valid_cooldown_frames,
        decisions=sequence_of_auto_decisions(min_size=2, max_size=30),
    )
    def test_auto_switches_within_cooldown_are_rejected(
        self, cooldown_frames: int, decisions: list[CameraDecision]
    ) -> None:
        """FOR ALL auto decisions submitted within cooldown, should_allow_switch returns False.

        After a switch is approved, all subsequent AUTO decisions within
        the cooldown window MUST be rejected.
        """
        hf = HysteresisFilter(cooldown_frames=cooldown_frames, fps=30.0)

        # Submit first decision — should be allowed (initial state has expired cooldown)
        first_result = hf.should_allow_switch(decisions[0])
        assert first_result is True, "First AUTO decision should always be allowed"

        # The remaining decisions are submitted one per frame (each call advances 1 frame).
        # Any decision within the cooldown window must be rejected.
        last_approved_frame = hf.current_frame

        for decision in decisions[1:]:
            frames_since_last = hf.current_frame + 1 - last_approved_frame
            result = hf.should_allow_switch(decision)

            if frames_since_last < cooldown_frames:
                # Within cooldown → MUST be rejected
                assert result is False, (
                    f"AUTO switch at frame {hf.current_frame} should be REJECTED "
                    f"(only {frames_since_last} frames since last approved switch at "
                    f"frame {last_approved_frame}, cooldown is {cooldown_frames})"
                )
            else:
                # Cooldown expired → switch is allowed, update tracking
                if result:
                    last_approved_frame = hf.current_frame

    @given(
        cooldown_frames=valid_cooldown_frames,
        extra_frames_before=integers(min_value=0, max_value=50),
    )
    def test_exactly_at_cooldown_boundary_is_allowed(
        self, cooldown_frames: int, extra_frames_before: int
    ) -> None:
        """A switch exactly at the cooldown boundary (elapsed == cooldown_frames) is allowed."""
        hf = HysteresisFilter(cooldown_frames=cooldown_frames, fps=30.0)

        # First switch (allowed)
        first = CameraDecision(target_cam=1, reason="first", source_origin=SourceOrigin.AUTO)
        assert hf.should_allow_switch(first) is True

        # Advance frames via tick() until exactly cooldown_frames - 1 more
        # (we already consumed 1 frame for the first call)
        for _ in range(cooldown_frames - 1):
            hf.tick()

        # Now elapsed == cooldown_frames, so the next switch should be allowed
        second = CameraDecision(target_cam=2, reason="second", source_origin=SourceOrigin.AUTO)
        result = hf.should_allow_switch(second)
        assert result is True, (
            f"Switch at exactly cooldown boundary should be ALLOWED "
            f"(elapsed={hf.current_frame - 1} frames, cooldown={cooldown_frames})"
        )

    @given(
        cooldown_frames=valid_cooldown_frames,
        num_attempts=integers(min_value=1, max_value=80),
    )
    def test_all_auto_switches_within_cooldown_rejected(
        self, cooldown_frames: int, num_attempts: int
    ) -> None:
        """ALL automatic switches submitted one-per-frame within cooldown window are rejected.

        After the first approved switch, submitting `num_attempts` decisions
        (where num_attempts < cooldown_frames) should ALL be rejected.
        """
        assume(num_attempts < cooldown_frames)

        hf = HysteresisFilter(cooldown_frames=cooldown_frames, fps=30.0)

        # Approve first switch
        first = CameraDecision(target_cam=1, reason="initial", source_origin=SourceOrigin.AUTO)
        assert hf.should_allow_switch(first) is True

        # Submit num_attempts more auto decisions (each advances frame by 1)
        for i in range(num_attempts):
            decision = CameraDecision(
                target_cam=(i % 4) + 1,
                reason=f"attempt {i}",
                source_origin=SourceOrigin.AUTO,
            )
            result = hf.should_allow_switch(decision)
            assert result is False, (
                f"Attempt {i + 1}/{num_attempts} should be REJECTED "
                f"(within cooldown of {cooldown_frames} frames)"
            )

    @given(cooldown_frames=valid_cooldown_frames)
    def test_is_cooling_down_true_while_in_cooldown(
        self, cooldown_frames: int
    ) -> None:
        """While within cooldown, is_cooling_down is True and scene stays unchanged."""
        hf = HysteresisFilter(cooldown_frames=cooldown_frames, fps=30.0)

        # Approve first switch
        first = CameraDecision(target_cam=1, reason="initial", source_origin=SourceOrigin.AUTO)
        hf.should_allow_switch(first)

        # After should_allow_switch, elapsed = current_frame - last_switch_frame = 0.
        # We need to tick `cooldown_frames` times total for the cooldown to expire
        # (i.e., until elapsed >= cooldown_frames).
        # Check is_cooling_down is True for each frame within the cooldown window.
        for i in range(cooldown_frames - 1):
            assert hf.is_cooling_down is True, (
                f"is_cooling_down should be True at frame {hf.current_frame} "
                f"(cooldown has {hf.frames_remaining} frames remaining)"
            )
            hf.tick()

        # One more tick to reach exactly cooldown_frames elapsed
        assert hf.is_cooling_down is True, (
            f"is_cooling_down should still be True at last cooldown frame "
            f"(elapsed={hf.current_frame - hf._last_switch_frame}, "
            f"cooldown={cooldown_frames})"
        )
        hf.tick()

        # After cooldown expires (elapsed == cooldown_frames)
        assert hf.is_cooling_down is False, (
            "is_cooling_down should be False after cooldown expires"
        )
