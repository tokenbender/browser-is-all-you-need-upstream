"""Versioned coverage scope. These IDs are intentionally not GRPO reward kernels."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Topic:
    groups: tuple[str, ...]
    diagnostics: tuple[str, ...] = ()
    exclusions: tuple[str, ...] = ()
    variable_sampling_groups: tuple[str, ...] = ()
    reward_families: tuple[tuple[str, tuple[str, ...]], ...] = ()
    auxiliary_sources: tuple[str, ...] = ()
    reference_control: str | None = None

    def __post_init__(self):
        members = [group for _, groups in self.families for group in groups]
        if (len(members) != len(set(members)) or set(members) != set(self.groups)
                or len({name for name, _ in self.families}) != len(self.families)
                or any(not groups for _, groups in self.families)):
            raise ValueError("reward families must partition the required groups")

    @property
    def families(self):
        return self.reward_families or tuple((group, (group,)) for group in self.groups)


TOPICS = {
    "allergies": Topic(
        ("all_masks", "higher_bits", "query_stability"),
        exclusions=("Unknown allergen names: unspecified error behavior.",),
    ),
    "bank-account": Topic(
        ("initial_state", "lifecycle", "transaction_sequences", "valid_transactions", "rejected_state", "account_isolation"),
        ("concurrent_transactions",),
        ("Zero amounts: instructions reject them but the pinned reference accepts them.",
         "Concurrent open/close, integer overflow and proof of race freedom are not covered."),
        reward_families=(("initial_state", ("initial_state",)),
                         ("lifecycle", ("lifecycle",)),
                         ("transactions", ("valid_transactions", "transaction_sequences")),
                         ("rejected_state", ("rejected_state",)),
                         ("isolation", ("account_isolation",))),
    ),
    "circular-buffer": Topic(
        ("int_sequences", "string_sequences", "wide_type", "capacity_boundaries"),
        exclusions=("Zero capacity and types beyond int/string/long long are not covered.",),
        reward_families=(("value_types", ("int_sequences", "string_sequences", "wide_type")),
                         ("capacity_boundaries", ("capacity_boundaries",))),
        auxiliary_sources=("circular-buffer-extra.cpp",),
    ),
    "clock": Topic(
        ("canonical_creation", "formatting", "signed_updates", "update_contract", "value_equality", "copy_isolation"),
        reward_families=(("creation", ("canonical_creation", "formatting")),
                         ("updates", ("signed_updates", "update_contract")),
                         ("equality", ("value_equality", "copy_isolation"))),
        exclusions=("Inputs that overflow the pinned reference int arithmetic are excluded.",),
    ),
    "complex-numbers": Topic(
        ("direct_add", "direct_subtract", "direct_multiply", "direct_divide",
         "scalar_add", "scalar_subtract", "scalar_multiply", "scalar_divide", "identities_and_exponential"),
        reward_families=(("direct", ("direct_add", "direct_subtract", "direct_multiply", "direct_divide")),
                         ("scalar", ("scalar_add", "scalar_subtract", "scalar_multiply", "scalar_divide")),
                         ("identities", ("identities_and_exponential",))),
        exclusions=("Zero denominators, nonfinite inputs and exact stream formatting.",),
    ),
    "dnd-character": Topic(
        ("modifier_negative_odd", "modifier_negative_even", "modifier_nonnegative", "ability_range", "character_rules"),
        ("randomness_observation",),
        ("No deterministic proof of four-dice distribution through this public API.",
         "No prescribed RNG, exact random sequence or automatic statistical penalty."),
        variable_sampling_groups=("ability_range", "character_rules"),
        reward_families=(("modifiers", ("modifier_negative_odd", "modifier_negative_even", "modifier_nonnegative")),
                         ("ability_range", ("ability_range",)), ("character_rules", ("character_rules",))),
    ),
    "grade-school": Topic(
        ("insertion_orders", "generated_rosters", "read_stability_and_isolation"),
        exclusions=("Duplicate students: instructions and pinned reference disagree.",),
    ),
    "space-age": Topic(
        ("conversion_boundaries", "wide_seconds", "scaling_and_repeatability"),
        exclusions=("Negative input is outside the unsigned public interface.",),
    ),
    "yacht": Topic(
        ("ones", "twos", "threes", "fours", "fives", "sixes", "choice", "full_house",
         "four_of_a_kind", "yacht", "little_straight", "big_straight"),
        reward_families=(("faces", ("ones", "twos", "threes", "fours", "fives", "sixes")),
                         ("choice", ("choice",)), ("full_house", ("full_house",)),
                         ("four_of_a_kind", ("four_of_a_kind",)), ("yacht", ("yacht",)),
                         ("straights", ("little_straight", "big_straight"))),
        exclusions=("Invalid dice and unknown categories have no specified behavior.",),
    ),
    "sublist": Topic(
        ("equal_relation", "sublist_relation", "superlist_relation", "unequal_relation",
         "empty_lists", "overlaps_and_boundaries", "swap_and_repeatability"),
        reward_families=(("relations", ("equal_relation", "sublist_relation", "superlist_relation", "unequal_relation")),
                         ("empty_lists", ("empty_lists",)),
                         ("overlap", ("overlaps_and_boundaries",)),
                         ("repeatability", ("swap_and_repeatability",))),
        exclusions=("Nonempty relations exhaustive through length 4 over {-1,0,1,2}; empty inputs tested separately; not all inputs.",),
    ),
    "perfect-numbers": Topic(
        ("domain_errors", "unit_and_primes", "known_perfect", "bounded_domain",
         "square_boundaries", "wide_values"),
        reward_families=(("domain", ("domain_errors",)),
                         ("classification", ("unit_and_primes", "known_perfect", "bounded_domain")),
                         ("squares", ("square_boundaries",)),
                         ("wide_arithmetic", ("wide_values",))),
        reference_control="references/perfect-numbers",
        exclusions=("Public signed-int domain only; bounded exhaustive and sampled wide inputs, not all integers.",),
    ),
}
