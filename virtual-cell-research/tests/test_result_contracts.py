"""Adversarial regression tests; no model weights or network calls."""
import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('screen_common', ROOT / 'examples/lung_cancer/drug_screen/common.py')
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)


class ResultContracts(unittest.TestCase):
    def test_distinct_responses_equal_scores(self):
        r = np.array([[0, 1, 0], [0, 0, 1], [0, -1, 0.]])
        q = common.degeneracy_check(r, common.reversal_scores(r, [1, 0, 0])[2])
        self.assertEqual(q['prediction_status'], 'result_available')
        self.assertEqual(q['response_status'], 'varying')
        self.assertEqual(q['ranking_status'], 'unresolved')

    def test_proportional_responses_retain_amplitude(self):
        r = np.array([[1, 2, 3], [2, 4, 6], [10, 20, 30.]])
        q = common.degeneracy_check(r, common.reversal_scores(r, [1, 0, 0])[2])
        self.assertFalse(q['degenerate'])
        self.assertAlmostEqual(q['median_pairwise_response_cosine'], 1)

    def test_nan_is_condition_failure(self):
        q = common.degeneracy_check([[1, 0], [0, 1], [np.nan, np.nan]], [-1, 0, np.nan])
        self.assertEqual(q['prediction_status'], 'partial')
        self.assertEqual(q['invalid_condition_indices'], [2])
        self.assertEqual(q['unscored_condition_indices'], [2])

    def test_all_invalid_empty_and_single_condition(self):
        self.assertEqual(common.degeneracy_check([[np.inf]], [np.nan])['prediction_status'], 'failed')
        self.assertEqual(common.degeneracy_check([[1, 2]], [1])['response_status'], 'insufficient_conditions')
        self.assertEqual(common.degeneracy_check(np.empty((0, 2)), [])['prediction_status'], 'failed')

    def test_identical_responses_keep_predictions(self):
        q = common.degeneracy_check([[1, 2], [1, 2]], [0, 0])
        self.assertTrue(q['degenerate'])
        self.assertEqual(q['prediction_status'], 'result_available')
        self.assertEqual(q['ranking_status'], 'unresolved')

    def test_shared_disease_mask(self):
        r = np.array([[2., -1, 1000], [1, 1, 2000]])
        full = common.reversal_scores(r, [1, -1, np.nan])
        subset = common.reversal_scores(r[:, :2], [1, -1])
        np.testing.assert_allclose(full[0], subset[0])
        r[0, 2] = np.nan
        self.assertTrue(np.isnan(common.reversal_scores(r, [1, -1, np.nan])[0][0]))

    def test_top_selection_preserves_rank_ids_and_doses(self):
        meta = pd.DataFrame({'drug': ['A', 'B', 'C', 'B'], 'dose_uM': [1, 1, 1, 10]})
        r = np.arange(8).reshape(4, 2)
        top = common.top_response_table(meta, r, ['g1', 'g2'], ['C', 'B'], n=2)
        self.assertEqual(top.drug.tolist(), ['C', 'B', 'B'])
        np.testing.assert_equal(top[['g1', 'g2']].to_numpy(), r[[2, 1, 3]])
        with self.assertRaises(ValueError):
            common.top_response_table(meta, r, ['g1', 'g2'], ['unknown'])

    def test_condition_scores_can_resolve_while_drug_means_cancel(self):
        conditions = pd.DataFrame({'drug': ['A', 'A', 'B', 'B'], 'dose_uM': [1, 10, 1, 10]})
        response = np.array([[1., 0], [0, 1], [1, 0], [0, 1]])
        score = common.reversal_scores(response, [1, -1])[2]
        np.testing.assert_allclose(score, [-1 / np.sqrt(2), 1 / np.sqrt(2)] * 2)
        drug, quality = common.aggregate_drug_ranking(conditions, response, score)
        self.assertEqual(quality['condition_ranking_status'], 'available')
        self.assertEqual(quality['drug_ranking_status'], 'unresolved')
        np.testing.assert_allclose(drug.reversal_score_mean, [0., 0.], atol=0.)
        self.assertTrue(drug['rank'].isna().all())
        self.assertEqual(common.top_ranked_drugs(drug), [])
        top = common.top_response_table(conditions, response, ['g1', 'g2'], common.top_ranked_drugs(drug), n=None)
        self.assertTrue(top.empty)
        self.assertEqual(top.columns.tolist(), ['drug', 'dose_uM', 'g1', 'g2'])

    def test_tied_drugs_share_competition_rank_and_top_boundary(self):
        conditions = pd.DataFrame({'drug': ['B', 'C', 'A']})
        score = np.array([0.8, 0.4, 0.80005])
        response = np.column_stack([-score, np.sqrt(1 - score ** 2)])
        np.testing.assert_allclose(common.reversal_scores(response, [1, 0])[2], score)
        drug, quality = common.aggregate_drug_ranking(conditions, response, score)
        self.assertEqual(quality['drug_ranking_status'], 'available')
        self.assertEqual(drug.set_index('drug')['rank'].to_dict(), {'A': 1, 'B': 1, 'C': 3})
        self.assertEqual(drug.set_index('drug').rank_tie_size.to_dict(), {'A': 2, 'B': 2, 'C': 1})
        selected = common.top_ranked_drugs(drug, n=1)
        self.assertEqual(selected, ['A', 'B'])
        top = common.top_response_table(conditions, response, ['g1', 'g2'], selected, n=None)
        self.assertEqual(top.drug.tolist(), selected)
        shuffled, _ = common.aggregate_drug_ranking(conditions.iloc[::-1], response[::-1], score[::-1])
        self.assertEqual(shuffled.set_index('drug')['rank'].to_dict(), drug.set_index('drug')['rank'].to_dict())

    def test_partial_drug_scores_stay_diagnostic_without_survivor_only_ranks(self):
        conditions = pd.DataFrame({'drug': ['A', 'A', 'B', 'C']})
        response = np.array([[-1., 1.], [np.nan, 1.], [-1., 0.], [1., 0.]])
        score = common.reversal_scores(response, [1, -1])[2]
        drug, quality = common.aggregate_drug_ranking(conditions, response, score)
        by_id = drug.set_index('drug')
        self.assertEqual(quality['excluded_incomplete_drugs'], ['A'])
        self.assertEqual(by_id.loc['A', 'n_conditions'], 2)
        self.assertEqual(by_id.loc['A', 'n_scored_conditions'], 1)
        self.assertEqual(by_id.loc['A', 'score_status'], 'partial')
        self.assertAlmostEqual(by_id.loc['A', 'reversal_score_mean'], 1.)
        self.assertTrue(pd.isna(by_id.loc['A', 'rank']))
        self.assertEqual(common.top_ranked_drugs(drug), ['B', 'C'])
        conditions['condition_id'] = ['c0', 'c1', 'c2', 'c3']
        conditions['drug_ranking_status'] = conditions.drug.map(by_id.drug_ranking_status)
        by_condition, summary, _ = common.drug_result_tables(
            conditions, response, ['g1', 'g2'], score, scoring_status='descriptive_only',
            ranking_status=quality['drug_ranking_status'])
        self.assertEqual(by_condition.drug_ranking_status.tolist(),
                         ['not_available', 'not_available', 'available', 'available'])
        self.assertEqual(summary.set_index('drug').loc['A', 'drug_ranking_status'], 'not_available')

    def test_skipped_scoring_and_empty_screens_do_not_publish_drug_ranks(self):
        for names, response, score in ((['A', 'B'], [[1., 0], [0, 1]], [np.nan, np.nan]),
                                      ([], np.empty((0, 2)), [])):
            with self.subTest(drugs=names):
                drug, quality = common.aggregate_drug_ranking(pd.DataFrame({'drug': names}), response, score)
                self.assertEqual(quality['drug_ranking_status'], 'not_available')
                self.assertTrue(drug['rank'].isna().all())
                self.assertEqual(common.top_ranked_drugs(drug), [])

    def test_single_condition_direction_does_not_require_candidate_ranking(self):
        conditions = pd.DataFrame({'condition_id': ['c0'], 'drug': ['A']})
        for response, expected in (([[-1., 1.]], 'predicted_reversal'),
                                   ([[1., -1.]], 'no_predicted_reversal')):
            with self.subTest(expected=expected):
                score = common.reversal_scores(response, [1, -1])[2]
                self.assertAlmostEqual(abs(score[0]), 1.)
                drug, quality = common.aggregate_drug_ranking(conditions, response, score)
                self.assertEqual(quality['condition_ranking_status'], 'insufficient_conditions')
                self.assertEqual(quality['drug_ranking_status'], 'insufficient_drugs')
                self.assertTrue(drug['rank'].isna().all())
                by_condition, summary, _ = common.drug_result_tables(
                    conditions, response, ['g1', 'g2'], score, scoring_status='descriptive_only',
                    ranking_status=quality['drug_ranking_status'])
                self.assertEqual(by_condition.iloc[0].recovery_status, expected)
                self.assertEqual(summary.iloc[0].recovery_status, expected)
        near_zero, _, _ = common.drug_result_tables(
            conditions, [[1., 1.]], ['g1', 'g2'], [0.00001],
            scoring_status='descriptive_only', ranking_status='insufficient_drugs')
        self.assertEqual(near_zero.iloc[0].recovery_status, 'indeterminate')
        self.assertEqual(near_zero.iloc[0].recovery_reason, 'within_score_tolerance')

    def test_equal_positive_scores_keep_direction_but_collapsed_responses_do_not(self):
        conditions = pd.DataFrame({'condition_id': ['c0', 'c1'], 'drug': ['A', 'B']})
        response = np.array([[-1., 1.], [-2., 2.]])
        score = common.reversal_scores(response, [1, -1])[2]
        np.testing.assert_allclose(score, [1., 1.])
        drug, quality = common.aggregate_drug_ranking(conditions, response, score)
        self.assertEqual(quality['drug_ranking_status'], 'unresolved')
        by_condition, _, _ = common.drug_result_tables(
            conditions, response, ['g1', 'g2'], score, scoring_status='descriptive_only',
            ranking_status=quality['drug_ranking_status'])
        self.assertEqual(by_condition.recovery_status.tolist(), ['predicted_reversal'] * 2)
        collapsed, _, genes = common.drug_result_tables(
            conditions, [[-1., 1.], [-1., 1.]], ['g1', 'g2'], [1., 1.],
            scoring_status='descriptive_only', ranking_status='unresolved')
        self.assertEqual(collapsed.recovery_status.tolist(), ['indeterminate'] * 2)
        self.assertEqual(collapsed.recovery_reason.tolist(), ['response_indistinguishable'] * 2)
        self.assertTrue((genes.gene_response_status == 'diagnostic_only').all())

    def test_a549_export_reports_condition_and_drug_resolution_separately(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = common.RunDir('cancelled_means', base_dir=Path(tmp))
            response = np.array([[1., 0], [0, 1], [1, 0], [0, 1]])
            indexed = run.save_predictions(
                pd.DataFrame({'drug': ['A', 'A', 'B', 'B'], 'dose': [1, 10, 1, 10]}),
                ['g1', 'g2'], response, np.zeros(2), response)
            score = common.reversal_scores(response, [1, -1])[2]
            indexed['reversal_score'] = score
            indexed.to_csv(run.tables / 'a549_conditions.csv', index=False)
            drug, drug_check = common.aggregate_drug_ranking(indexed, response, score)
            drug.to_csv(run.tables / 'a549_drug_ranking.csv', index=False)
            (run.tables / 'scoring_metadata.json').write_text(json.dumps({'status': 'descriptive_only'}), encoding='utf-8')
            run.finish({'backend': 'synthetic'}, {
                'backend': 'synthetic', 'status': 'result_available',
                'condition_ranking_status': 'available', 'drug_ranking_status': drug_check['drug_ranking_status'],
                'ranking_status': drug_check['drug_ranking_status'], 'validation_status': 'unvalidated'})
            summary = pd.read_csv(run.tables / 'drug_recovery_summary.csv')
            self.assertEqual(summary.recovery_status.tolist(), ['condition_dependent'] * 2)
            by_condition = pd.read_csv(run.tables / 'drug_recovery_by_condition.csv')
            self.assertEqual(by_condition.dose.tolist(), [1, 10, 1, 10])
            figures = pd.read_csv(run.figures / 'figure_manifest.csv').set_index('figure_id')
            self.assertEqual(figures.loc['drug_ranking', 'status'], 'skipped')
            self.assertIn('drug_ranking_status=unresolved', figures.loc['drug_ranking', 'reason'])
            report = (run.root / 'report.md').read_text(encoding='utf-8')
            self.assertIn('condition ranking: available; drug ranking: unresolved', report)
            self.assertIn('validation: unvalidated', report)

    def test_drug_recovery_and_each_conditions_top_genes(self):
        genes = [f'g{i}' for i in range(35)]
        conditions = pd.DataFrame({
            'condition_id': ['c0', 'c1', 'c2', 'c3', 'c4'],
            'drug': ['A', 'A', 'B', 'C', 'D'],
            'dose_uM': [1, 10, 1, 1, 1]})
        response = np.array([
            np.arange(35), -np.arange(35), np.ones(35),
            np.full(35, np.nan), np.zeros(35)], dtype=float)
        by_condition, by_drug, top = common.drug_result_tables(
            conditions, response, genes, [0.5, -0.2, -0.4, np.nan, 0.1],
            scoring_status='descriptive_only', ranking_status='available')
        self.assertEqual(by_condition.recovery_status.tolist(), [
            'predicted_reversal', 'no_predicted_reversal',
            'no_predicted_reversal', 'indeterminate', 'indeterminate'])
        self.assertEqual(by_drug.set_index('drug').loc['A', 'recovery_status'], 'condition_dependent')
        self.assertEqual(by_drug.set_index('drug').loc['C', 'recovery_status'], 'indeterminate')
        self.assertEqual(top[top.condition_id == 'c0'].gene.tolist(),
                         [f'g{i}' for i in range(34, 4, -1)])
        self.assertEqual(top[top.condition_id == 'c1'].iloc[0].effect_direction, 'down')
        self.assertFalse((top.condition_id == 'c3').any())
        self.assertFalse((top.condition_id == 'c4').any())

        unavailable, summary, top_unavailable = common.drug_result_tables(
            conditions, response, genes, [0.5, -0.2, -0.4, np.nan, 0.1],
            scoring_status='skipped', ranking_status='not_available')
        self.assertTrue((unavailable.recovery_status == 'indeterminate').all())
        self.assertTrue((summary.recovery_status == 'indeterminate').all())
        self.assertEqual(len(top_unavailable), len(top))

    def test_drug_result_export_uses_saved_condition_order(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(common, 'ROOT', Path(tmp)):
            run = common.RunDir('drug_results')
            response = np.array([[2., -1.], [-3., 1.]])
            indexed = run.save_predictions(
                pd.DataFrame({'drug': ['A', 'B'], 'dose_uM': [1, 10]}),
                ['g1', 'g2'], response, np.zeros(2), response)
            indexed['reversal_score'] = [0.5, -0.5]
            indexed.to_csv(run.tables / 'conditions.csv', index=False)
            (run.tables / 'scoring_metadata.json').write_text(
                json.dumps({'status': 'descriptive_only'}), encoding='utf-8')
            run.finish({'backend': 'synthetic'},
                       {'backend': 'synthetic', 'status': 'result_available',
                        'ranking_status': 'available'})
            summary = pd.read_csv(run.tables / 'drug_recovery_summary.csv').set_index('drug')
            self.assertEqual(summary.loc['A', 'recovery_status'], 'predicted_reversal')
            self.assertEqual(summary.loc['B', 'recovery_status'], 'no_predicted_reversal')
            self.assertEqual(pd.read_csv(run.tables / 'drugs_predicted_reversal.csv').drug.tolist(), ['A'])
            self.assertEqual(pd.read_csv(run.tables / 'drugs_no_predicted_reversal.csv').drug.tolist(), ['B'])
            top = pd.read_csv(run.tables / 'drug_top30_genes.csv')
            self.assertEqual(top.groupby('drug').size().to_dict(), {'A': 2, 'B': 2})
            self.assertIn('药物筛选结果', (run.root / 'report.md').read_text(encoding='utf-8'))
            self.assertIn('tables/drug_top30_genes.csv', (run.root / 'report.md').read_text(encoding='utf-8'))

    def test_full_prediction_roundtrip_and_errors(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(common, 'ROOT', Path(tmp)):
            run = common.RunDir('test')
            baseline = np.array([2., 3.])
            prediction = np.array([[3, 4], [4, 5], [np.nan, 4.]])
            response = prediction - baseline
            indexed = run.save_predictions(pd.DataFrame({'drug': ['A', 'B', 'C']}),
                                           ['g1', 'g2'], prediction, baseline, response)
            with np.load(run.raw / 'predictions.npz', allow_pickle=False) as saved:
                np.testing.assert_allclose(saved['response'], response, equal_nan=True)
                self.assertEqual(saved['condition_id'].tolist(), indexed.condition_id.tolist())
            self.assertEqual(len(pd.read_csv(run.tables / 'all_conditions_gene_response.csv.gz')), 3)
            q = run.condition_quality(indexed, response, [1, 2, np.nan])
            self.assertEqual(q['prediction_status'], 'partial')
            self.assertEqual(run.errors[0]['condition_id'], indexed.iloc[2].condition_id)
            with self.assertRaises(ValueError):
                run.save_predictions(pd.DataFrame({'drug': ['A', 'B', 'C']}),
                                     ['g1', 'g2'], prediction, baseline, response + 1)
            self.assertNotEqual(common.RunDir('test').root, run.root)

    def test_repeated_run_creation_with_fixed_clock_preserves_previous_files(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(common, 'datetime') as clock:
            clock.now.return_value = datetime(2026, 11, 13, 12, 30, 45, 123456)
            first = common.RunDir('repeated', base_dir=Path(tmp))
            (first.raw / 'marker.txt').write_text('original result', encoding='utf-8')
            second = common.RunDir('repeated', base_dir=Path(tmp))
            (second.raw / 'marker.txt').write_text('new result', encoding='utf-8')
            self.assertNotEqual(first.root, second.root)
            self.assertNotEqual(first.run_id, second.run_id)
            for run in (first, second):
                self.assertEqual(run.run_id, run.root.name)
                self.assertTrue(run.run_id.startswith('repeated_20261113T123045123456_'))
                self.assertTrue(all(folder.is_dir() for folder in (run.raw, run.tables, run.figures)))
            self.assertEqual((first.raw / 'marker.txt').read_text(encoding='utf-8'), 'original result')
            self.assertEqual((second.raw / 'marker.txt').read_text(encoding='utf-8'), 'new result')

    def test_concurrent_run_creation_with_fixed_clock_is_atomic(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(common, 'datetime') as clock:
            clock.now.return_value = datetime(2026, 11, 13, 12, 30, 45, 123456)

            def create(index):
                run = common.RunDir('parallel', base_dir=Path(tmp))
                (run.raw / 'marker.txt').write_text(str(index), encoding='utf-8')
                return run, index

            with ThreadPoolExecutor(max_workers=8) as pool:
                runs = list(pool.map(create, range(32)))
            self.assertEqual(len({run.root for run, _ in runs}), 32)
            self.assertEqual(len({run.run_id for run, _ in runs}), 32)
            for run, index in runs:
                self.assertEqual(run.run_id, run.root.name)
                self.assertEqual((run.raw / 'marker.txt').read_text(encoding='utf-8'), str(index))

    def test_run_id_rejects_path_components_before_creating_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            for invalid in ('', ' ', '.', '..', '../outside', 'nested/run', 'nested\\run',
                            '/absolute', 'C:\\outside', 'C:relative', 'bad:name', 'bad?name', '\0', '\x1f', None, 123):
                with self.subTest(run_id=invalid), self.assertRaisesRegex(ValueError, 'single filename component'):
                    common.RunDir(invalid, base_dir=Path(tmp))
            self.assertFalse((Path(tmp) / 'results').exists())
            run = common.RunDir('肺癌 筛选', base_dir=Path(tmp))
            self.assertEqual(run.run_id, run.root.name)
            self.assertTrue(run.run_id.startswith('肺癌 筛选_'))

    def test_scoring_requires_scale_contract(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(common, 'ROOT', Path(tmp)), patch.object(common, 'DATA', Path(tmp)):
            run = common.RunDir('test')
            result = run.score_response(np.array([[1, 2.]]), np.array([1, -1.]), 'backend')
            self.assertTrue(np.isnan(result[2]).all())
            meta = json.loads((run.tables / 'scoring_metadata.json').read_text(encoding='utf-8'))
            self.assertEqual(meta['status'], 'skipped')

    def test_finish_exports_figures_and_strict_json(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(common, 'ROOT', Path(tmp)):
            run = common.RunDir('integration')
            response = np.array([[1., -1, 0], [0, 1, -1], [-1, 0, 1]])
            indexed = run.save_predictions(pd.DataFrame({'drug': ['A', 'B', 'C']}),
                                           ['g1', 'g2', 'g3'], response, np.zeros(3), response)
            q = run.condition_quality(indexed, response, [np.nan] * 3)
            run.finish({'backend': {'name': 'test'}},
                       {'backend': 'test', 'status': q['prediction_status'],
                        'ranking_status': q['ranking_status'], 'range': [np.nan, np.nan]})
            records = pd.read_csv(run.figures / 'figure_manifest.csv').set_index('figure_id')
            self.assertEqual(records.loc['drug_response_heatmap', 'status'], 'generated')
            self.assertEqual(records.loc['response_similarity', 'status'], 'generated')
            self.assertEqual(records.loc['reversal_null', 'status'], 'skipped')
            def reject_constant(s):
                raise ValueError(s)
            result = json.loads((run.root / 'validation.json').read_text(encoding='utf-8'), parse_constant=reject_constant)
            self.assertEqual(result['range'], [None, None])
            self.assertTrue((run.root / 'provenance.json').exists())

    def test_scoring_contract_source_binding(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(common, 'ROOT', Path(tmp)), patch.object(common, 'DATA', Path(tmp)):
            base = Path(tmp)
            source = base / 'GSE81089_landmark978_signature.csv'
            source.write_text('gene_symbol,tumor_minus_normal_log2\nA,1\nB,-1\n', encoding='utf-8')
            contract = {'metric': 'negative_cosine', 'response_scale': 'test effect',
                        'disease_scale': 'test effect', 'scale_justification': 'same synthetic scale',
                        'comparison_scope': 'synthetic unit test', 'minimum_common_genes': 2,
                        'disease_source_sha256_16': common.sha16(source)}
            (base / 'test_scoring_contract.json').write_text(json.dumps(contract), encoding='utf-8')
            with patch.object(common, 'DISEASE_VEC', base / 'vector.csv'):
                run = common.RunDir('scoring')
                score = run.score_response(np.array([[-1., 1]]), np.array([1., -1]), 'test')[2]
                self.assertAlmostEqual(score[0], 1)
                source.write_text('changed', encoding='utf-8')
                score = run.score_response(np.array([[-1., 1]]), np.array([1., -1]), 'test')[2]
                self.assertTrue(np.isnan(score[0]))

    def test_disease_missing_distinct_from_real_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            pd.DataFrame({'gene_symbol': ['A', 'B'], 'tumor_minus_normal_log2': [0., 2.]}).to_csv(
                base / 'GSE81089_landmark978_signature.csv', index=False)
            with patch.object(common, 'DISEASE_VEC', base / 'old_vector.csv'):
                d, count = common.load_disease_direction(['A', 'B', 'C'])
            self.assertEqual(count, 1)
            self.assertEqual(d[0], 0.)
            self.assertTrue(np.isnan(d[2]))

    def test_baseline_normalizes_full_transcriptome_but_densifies_only_projected_genes(self):
        events = []
        matrix = np.array([[1., 1000., 3.], [4., 2000., 6.]])

        class SparseInput:
            def toarray(self):
                raise AssertionError('full-transcriptome dense allocation is forbidden')

            def __getitem__(self, key):
                events.append(('project', key[1]))
                return types.SimpleNamespace(toarray=lambda: matrix[key])

        full = SparseInput()
        data = types.SimpleNamespace(X=full, var_names=pd.Index(['g2', 'unused', 'g1']),
                                     obs_names=pd.Index(['cell1', 'cell2']), n_obs=2, n_vars=3)

        def normalize(adata, target_sum):
            self.assertIs(adata.X, full)
            events.append(('normalize_full', target_sum))

        def log(adata):
            self.assertIs(adata.X, full)
            events.append(('log_full',))

        scanpy = types.SimpleNamespace(read_h5ad=lambda path: data,
                                       pp=types.SimpleNamespace(normalize_total=normalize, log1p=log))
        with patch.dict('sys.modules', {'scanpy': scanpy}):
            baseline, info = common.load_baseline(['g1', 'g2'])
        self.assertEqual(events, [('normalize_full', 10000.), ('log_full',), ('project', [2, 0])])
        np.testing.assert_array_equal(baseline.to_numpy(), [[3., 1.], [6., 4.]])
        self.assertEqual(info['scrna_genes_total'], 3)

    def test_duplicate_baseline_or_model_gene_ids_are_rejected(self):
        for input_ids, model_ids, reason in ((['g1', 'g1'], ['g1'], 'duplicate input'),
                                             (['g1', 'g2'], ['g1', 'g1'], 'model gene IDs')):
            with self.subTest(input=input_ids, model=model_ids):
                data = types.SimpleNamespace(var_names=pd.Index(input_ids))
                scanpy = types.SimpleNamespace(read_h5ad=lambda path: data)
                with patch.dict('sys.modules', {'scanpy': scanpy}), self.assertRaisesRegex(ValueError, reason):
                    common.load_baseline(model_ids)


if __name__ == '__main__':
    unittest.main()
