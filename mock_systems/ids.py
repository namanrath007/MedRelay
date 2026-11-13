"""
Each mock system uses its OWN patient identifier, just like real hospitals.
Linking them is part of the integration problem the agents must solve.

  truth id      P00001
  legacy EHR    MRN 400001          (stored in PT_MSTR.PT_ID)
  REST portal   MBR-007919          (portal member id; also carries extRef = MRN)
  HL7 lab feed  PID-3 = 400001^^^LEGACYEHR^MR   (refers back to the MRN)
"""


def to_mrn(truth_id: str) -> str:
    return str(400000 + int(truth_id[1:]))


def to_member_id(truth_id: str) -> str:
    return f"MBR-{(int(truth_id[1:]) * 7919) % 1_000_000:06d}"
