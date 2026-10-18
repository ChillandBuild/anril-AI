"""Every Phase 1 call-scoring threshold. Phase 6 turns these into admin settings."""

RULES_VERSION = "v1"

# Every AI judgement call (sorting, marking, the CRM check) is made this many times
# with the identical prompt at temperature 0, and decided by majority — the same
# transcript must get the same answer every time (method doc Step 1).
AI_VOTES = 3

# Step 1 — sorting
MIN_SCORED_SECONDS = 30
MIN_SIGNS = 2

# Two-track audio (TeleCMI stereo: right = telecaller, left = customer)
TELECALLER_CHANNEL = 1
FRAME_SECONDS = 0.1
SPEECH_MIN_LEVEL = 300          # mean |sample| a frame must reach to count as speech
NOISE_FLOOR_MULTIPLIER = 4      # speech must be this many times the track's own quiet level
MIN_SPEECH_RUN_S = 0.2
MERGE_GAP_S = 0.3
OVERLAP_MIN_S = 1.0
TELECALLER_RUN_MIN_S = 1.0
MONOLOGUE_GAP_S = 1.5   # pauses shorter than this don't end a telecaller monologue
DEAD_AIR_MIN_S = 3.0    # a silence must last this long to count as dead air
SNAP_WINDOW_S = 3.0

# Talk share / interruptions (defaults from the method document)
TALK_SHARE_MIN_WORDS = 50
TALK_SHARE_PASSIVE = 30
TALK_SHARE_HEALTHY_MAX = 65
TALK_SHARE_HIGH_MAX = 75
INTERRUPTIONS_GOOD_MAX = 1
INTERRUPTIONS_SOMETIMES_MAX = 3

# Step 2 — marking
CHECK_MARKS = {
    "opening": 5, "courtesy": 10, "questions": 15, "listening": 10, "product_info": 15,
    "doubts": 10, "clarity": 10, "next_step": 10, "decision": 8, "crm_update": 7,
}
LEVEL_SHARE = {"excellent": 1.0, "good": 0.75, "partial": 0.5, "poor": 0.25, "missing": 0.0}
LEVEL_ORDER = ("missing", "poor", "partial", "good", "excellent")
WRAPUP_CUTOFF_HOURS = 2
QUOTE_MAX_CHARS = 240

# Warnings
ALERT_RATE_LIMIT_PER_HOUR = 1
LEAD_SOURCE_MIN_CALLS = 10
LEAD_SOURCE_BAD_RATE = 0.30
MORNING_SUMMARY_HOUR_IST = 9
