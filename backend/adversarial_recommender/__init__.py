"""
Continuous Adversarial Recommendation Engine.

Five stages -- attack generation, gap characterization, recommendation
drafting, impact simulation, and a human approval gate -- built around one
hard rule that nothing here may violate: this subsystem recommends, it
never modifies live detection logic. See docs/ADVERSARIAL_RECOMMENDER.md
for the full design and docs/ARCHITECTURE.md for how it fits the rest of
the system.

Cites "A multi-rounded adversarial scenario for graph-based promo fraud
detection" (Springer, Social Network Analysis and Mining, Dec 2025,
DOI 10.1007/s13278-025-01566-0) as the basis for the round-over-round
methodology in attack_generator.py.
"""
