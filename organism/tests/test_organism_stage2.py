"""Comprehensive automated tests for ORGANISM Stage 2 adaptive learning, calibration, and memory."""

from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path

from organism.config.settings import OrganismConfig, load_config
from organism.evaluation.benchmarks import run_all_benchmarks, run_stage2_benchmarks
from organism.kernel.contracts import CognitiveEvent, CycleStatus, EpistemicType, MemoryStatus, TrustLevel
from organism.kernel.runtime import CognitiveKernel


class OrganismStage2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.state_path = Path(self.tmp_dir.name)
        self.config: OrganismConfig = load_config(state_dir_override=self.state_path)
        self.kernel = CognitiveKernel(config=self.config)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_world_model_learns_and_improves_probability_and_brier(self) -> None:
        probs: list[float] = []
        briers: list[float] = []
        for i in range(1, 7):
            cp = self.kernel.run_cycle(
                CognitiveEvent(
                    event_id=f"ev_wm_{i}",
                    operation_id=f"op_wm_{i}",
                    source="test_operator",
                    trust_level=TrustLevel.TRUSTED_OPERATOR,
                    event_type="math",
                    content=f"calc: {i} + {i * 2}",
                )
            )
            self.assertEqual(cp.status, CycleStatus.COMPLETED)
            probs.append(float(cp.prediction["predicted_probability"]))
            briers.append(float(cp.comparison["brier_term"]))

        self.assertGreater(probs[-1], probs[0])
        self.assertLess(briers[-1], briers[0])
        self.assertLess(float(cp.metacognition["brier_score"]), 0.25)

    def test_metacognition_four_axes_and_abstention_on_unknown_query(self) -> None:
        cp = self.kernel.run_cycle(
            CognitiveEvent(
                event_id="ev_unk_1",
                operation_id=f"op_{uuid.uuid4().hex[:8]}",
                source="test_operator",
                trust_level=TrustLevel.TRUSTED_OPERATOR,
                event_type="query",
                content="query: nonexistent_telemetry_field_abc",
            )
        )
        self.assertTrue(cp.metacognition["refrain_recommended"])
        self.assertIn("no_supporting_memory_records", cp.metacognition["refrain_reasons"])
        axes = cp.metacognition["confidence_axes"]
        self.assertIn("prediction_confidence", axes)
        self.assertIn("source_confidence", axes)
        self.assertIn("memory_confidence", axes)
        self.assertIn("reasoning_confidence", axes)

    def test_evidence_lifecycle_blocks_single_source_and_requires_corroboration(self) -> None:
        # 1st observation from trusted_operator must stay CANDIDATE
        self.kernel.run_cycle(
            CognitiveEvent(
                event_id="ev_c1",
                operation_id=f"op_{uuid.uuid4().hex[:8]}",
                source="station_north",
                trust_level=TrustLevel.TRUSTED_OPERATOR,
                event_type="assertion",
                content="fact: telemetry_link is nominal",
            )
        )
        fact = self.kernel.store.find_semantic_triple("telemetry_link", "is", "nominal")
        self.assertIsNotNone(fact)
        assert fact is not None
        self.assertEqual(fact["status"], MemoryStatus.CANDIDATE.value)

        # Duplicate observation from identical source cannot promote to VERIFIED
        self.kernel.run_cycle(
            CognitiveEvent(
                event_id="ev_c2",
                operation_id=f"op_{uuid.uuid4().hex[:8]}",
                source="station_north",
                trust_level=TrustLevel.TRUSTED_OPERATOR,
                event_type="assertion",
                content="fact: telemetry_link is nominal",
            )
        )
        after_dup = self.kernel.store.find_semantic_triple("telemetry_link", "is", "nominal")
        assert after_dup is not None
        self.assertNotEqual(after_dup["status"], MemoryStatus.VERIFIED.value)

        # 2nd independent source promotes to VERIFIED
        self.kernel.run_cycle(
            CognitiveEvent(
                event_id="ev_c3",
                operation_id=f"op_{uuid.uuid4().hex[:8]}",
                source="station_south",
                trust_level=TrustLevel.INTERNAL_SYSTEM,
                event_type="assertion",
                content="fact: telemetry_link is nominal",
            )
        )
        verified = self.kernel.store.find_semantic_triple("telemetry_link", "is", "nominal")
        assert verified is not None
        self.assertEqual(verified["status"], MemoryStatus.VERIFIED.value)
        self.assertGreaterEqual(int(verified["evidence_count"]), 2)

        # Untrusted contradiction is REJECTED and never invalidates VERIFIED fact
        self.kernel.run_cycle(
            CognitiveEvent(
                event_id="ev_poison",
                operation_id=f"op_{uuid.uuid4().hex[:8]}",
                source="untrusted_mirror",
                trust_level=TrustLevel.UNTRUSTED_EXTERNAL,
                event_type="assertion",
                content="fact: telemetry_link is offline",
            )
        )
        still_verified = self.kernel.store.find_semantic_triple("telemetry_link", "is", "nominal")
        assert still_verified is not None
        self.assertEqual(still_verified["status"], MemoryStatus.VERIFIED.value)
        all_rows = self.kernel.store.list_semantic_facts(include_invalidated=True, include_forgotten=True, limit=30)
        rejected = [r for r in all_rows if r["object_value"] == "offline"]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["status"], MemoryStatus.REJECTED.value)

    def test_active_learning_eig_and_safe_probe_execution(self) -> None:
        cp = self.kernel.run_cycle(
            CognitiveEvent(
                event_id="ev_al_1",
                operation_id=f"op_{uuid.uuid4().hex[:8]}",
                source="probe_alpha",
                trust_level=TrustLevel.TRUSTED_OPERATOR,
                event_type="assertion",
                content="fact: gyro_drift is minimal",
            )
        )
        self.assertGreaterEqual(cp.active_learning.get("proposals_count", 0), 1)
        exps = self.kernel.store.list_active_experiments(limit=10)
        self.assertGreaterEqual(len(exps), 1)
        target_exp = exps[0]
        self.assertGreater(float(target_exp["expected_info_gain"]), 0.0)

        executed = self.kernel.active_learning.run_safe_experiment(target_exp["experiment_id"])
        self.assertIsNotNone(executed)
        assert executed is not None
        self.assertEqual(executed["status"], "EXECUTED")
        self.assertGreater(float(executed["info_gain_realized"]), 0.0)

    def test_continual_learning_fisher_anchors_and_forgetting(self) -> None:
        for i in range(4):
            self.kernel.run_cycle(
                CognitiveEvent(
                    event_id=f"ev_cl_{i}",
                    operation_id=f"op_cl_{i}",
                    source="test_operator",
                    trust_level=TrustLevel.TRUSTED_OPERATOR,
                    event_type="math",
                    content=f"calc: 5 + {i}",
                )
            )
        anchored = self.kernel.continual.consolidate_fisher_anchors()
        self.assertGreaterEqual(anchored, 1)
        replay = self.kernel.continual.replay_rehearsal(batch_size=8)
        self.assertGreaterEqual(replay["rehearsed_count"], 1)

        # Insert stale candidate facts and verify selective forgetting preserves high-confidence/verified ones
        for k in range(5):
            self.kernel.store.insert_semantic_fact(
                subject=f"clutter_{k}",
                predicate="is",
                object_value="ephemeral",
                epistemic_type=EpistemicType.HYPOTHESIS,
                confidence=0.32,
                status=MemoryStatus.CANDIDATE,
                source_episode_id="ep_none",
            )
        forget = self.kernel.retriever.apply_controlled_forgetting(max_retain=2)
        self.assertGreaterEqual(forget["forgotten_count"], 3)

    def test_stage2_and_combined_benchmarks_with_historical_comparison(self) -> None:
        first = run_stage2_benchmarks(record_to_store=self.kernel)
        self.assertEqual(first["passed"], first["total"])
        self.assertEqual(first["score"], 1.0)

        combined = run_all_benchmarks(record_to_store=self.kernel)
        self.assertEqual(combined["passed"], combined["total"])
        self.assertEqual(combined["score"], 1.0)
        self.assertFalse(combined["historical_comparison"]["regression_detected"])
        self.assertGreaterEqual(len(self.kernel.store.list_organ_metrics()), 0)


if __name__ == "__main__":
    unittest.main()
