from enum import StrEnum


class VerificationStatus(StrEnum):
    VERIFIED = "verified"
    USER_PROVIDED = "user_provided"
    INFERRED_UNVERIFIED = "inferred_unverified"


class SourceType(StrEnum):
    MASTER_CV = "master_cv"
    USER_INPUT = "user_input"
    SYSTEM_INFERENCE = "system_inference"
