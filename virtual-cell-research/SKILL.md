---
name: virtual-cell-research
description: Orchestrate extensible virtual cell research workflows for transcriptomic and single-cell data. Use for data preparation and input audits, observed-response analysis, model-based gene or compound perturbations, prediction evaluation and split audits, interpretation of existing results, public-case reproduction, and method or adapter integration. Gene knockout, overexpression and drug screening are representative applications. Execute compatible analysis routes, preserve full results and provenance, and report implementation, quality and independent-validation status separately.
---

# Virtual Cell Research

Organize extensible virtual cell research workflows around the research question. Enter data preparation and auditing, observed-response analysis, model perturbation, prediction evaluation, interpretation of existing results, or public-case reproduction according to the user's current objective. Run these entry points individually or combine them into a complete analysis. Treat gene knockout, overexpression and drug screening as representative applications within this broader scope.

Reuse the existing data, model and evaluation contracts. When adding a data type, backend or method, first verify its sources, input/output definitions and implementation status. Follow the contribution guidelines to adapt and validate it before registering the capability. Record unimplemented routes honestly; extension goals do not substitute for execution evidence. Preserve complete responses, applicable figures, quality checks and provenance.

## Accept files and tasks; execute and deliver the analysis

Accept data files or an accessible local directory together with a research objective in natural language. Perform environment checks, dependency preparation, selected resource retrieval, script execution, plotting and result organization as the Agent. Providing only code, commands or an action plan does not complete an analysis task. If an installation request also includes data and a research objective, continue with that task after installation. For installation-only requests, verify the complete Skill's installation location and loadability, then explain how to provide data and begin an analysis.

Inspect the files and existing records before requesting information that materially affects scientific interpretation. If files, the repository or an execution environment are inaccessible, identify the blocked step and the conditions needed to proceed. Reuse an already authorized connection or complete local copy when available. After execution, show the report and main figures, provide access to full results and run records, and explain the completed scope. Operate the routine workflow as the Agent; use technical reproduction commands for execution and troubleshooting without requiring the user to run them line by line.

## 1. Select an entry point and resolve material gaps

Infer the entry point from the current request and proceed directly when it is clear:

| Entry point | Work to perform | Evidence of completion |
| --- | --- | --- |
| Prepare user data | Organize CSV/TSV/H5AD using declared scales and identifiers; preserve original values and complete axes | A new H5AD, data description, checks and provenance; successful preparation does not establish model readiness |
| Execute a model | Check user/reference data and model resources; execute a compatible route | Commands, logs, versions, native model outputs and checks from this run |
| Evaluate predictions | Align observed and predicted data, compare simple baselines and inspect training/evaluation membership | Complete metrics on the same scale, membership audits and an explicit scientific-validation status |
| Learn from real observations | By default, recommend the HT115 treatment/control walkthrough; explicitly retrieve selected resources and compute contrasts | New provenance, complete observed contrasts, condition indices and QC; this is not model inference |
| Audit inputs | Verify whether data meet the input assumptions of a specified route | Check records and specific blocking reasons; an input problem is not a model failure |
| Review existing or historical results | Read reports, manifests, tables, figures and corrections | Identify the existing artifacts inspected; do not claim a new execution |
| Integrate a method or adapter | Follow the contribution guidelines to verify sources, input/output contracts and implementation scope | Register the capability only after adaptation and contract validation; preserve execution evidence and limitations |

When data and an objective are already available, handle that task directly without requiring a walkthrough first. Read [User data](references/user-data.md) for CSV/TSV/H5AD preparation, [Prediction evaluation](references/prediction-evaluation.md) when observations and predictions are available, and [Result interpretation](references/result-reading.md) when explaining a supported existing run.

For first use, read [First run](references/first-run.md) and select a specific case from the [Case catalog](cases/README.md). `python scripts/cases.py list`, `show <case-id>` and `validate` run offline. Only an explicit `fetch <case-id> --asset <asset-id> --output-dir <new-directory>` downloads a single resource, with a default limit of 64 MiB. Do not download every case automatically.

When the user wants to see actual case outputs, read [Public case results](cases/gallery/README.md). Retrieve public data and execute the analysis using that case's commands, then invoke its plotting entry point. Preserve complete source tables, display-selection rules, shared axes or color scales, and numerical checks for the current run. Accompany each figure with a brief research question and reading guide; distinguish observations, model simulations and prediction evaluations.

For an observed-response example, execute the HT115 walkthrough in `scripts/observed_prnet_case.py`: approximately 3.14 MB of real source data, observed contrasts for 661 treatment profiles against their specified controls, with 20 control profiles and 978 genes retained. Of these, 338 treatment profiles are paired across RNA plates; explain the possible batch effects. This step does not load or run PRnet. Do not replace a model-analysis task with a walkthrough when the user has specified inputs and objectives.

**Inspect first, then ask.** Carry forward the data, objectives, baselines, models and environments already supplied. Inspect metadata in accessible files, processing records and available model environments. At startup, ask at most one brief, consolidated round of questions, limited to missing information that changes the research question or scientific interpretation and cannot be verified from existing information. Examples include target genes, separate versus joint perturbations, the actual cell background, controls, a compound library or a CellOracle OE setting. Do not repeat a six-field intake form.

For an unspecified model, compatible interpreter, working directory or routine run parameter, select an adjustable default based on the research objective, inputs and resources; briefly explain and record the choice. Run directly once the requirements are met, without asking again for confirmation to start. Do not guess genes/compounds, the provenance of raw counts, a disease reference or the biological definition of OE, or silently replace a user-specified model, baseline, target or task. If a critical scientific input remains unclear, complete the checks, report the blocker and do not start the affected inference. A material input contradiction discovered later may warrant a focused follow-up question; do not request known settings again.

## 2. Check inputs and actual available capabilities

Use the [Input contracts](references/input-contracts.md) to check format, scale, species, gene IDs, cell background, target coverage, controls and compound/dose information. Record missing values separately from measured zeros. Do not infer an unknown scale from numerical appearance or silently zero-fill required missing genes. A disease reference is required only for comparisons with a disease expression direction.

When preparing user tables or a specified H5AD expression layer, use the actual parameters of `scripts/prepare_user_data.py` and record an explicit matrix orientation, scale and species. Check that metadata align by unique IDs. This step does not automatically normalize, select genes, deduplicate or resolve gene aliases; integer-looking values do not certify raw-count provenance. After writing a new data card and files, continue with model-specific checks.

For file-level checks, prepare a request using [Preflight and troubleshooting](docs/troubleshooting.md) and run `scripts/preflight.py`. H5AD checks inspect metadata only by default; explicitly setting `scan_h5ad_values: true` scans all stored values of the selected dense/CSR/CSC matrix in blocks. Value checks do not certify raw-count provenance, sparse indices, `n_counts` consistency or model compatibility. `incomplete` means required checks remain unfinished; `preflight_ready` covers only the limited preflight scope. Read blockers and unchecked items, then continue backend verification. A noninteger `raw_count` blocker in the Paul2015 tutorial file is input-audit evidence, not a failed model run.

| Route | Entry point provided in this repository | Scope and constraints |
| --- | --- | --- |
| CellOracle | Parameterized `examples/ko_oe/celloracle_run.py`; [Actual case from raw data to Gata1 KO](cases/celloracle-paul2015-gata1/README.md) | Requires raw single-cell counts, a matching GRN prior and a TF eligible for simulation; outputs simulated expression differences and state shifts |
| Geneformer | Parameterized `examples/ko_oe/geneformer_route.py` | This example is limited to a complete human raw transcriptome, matching tokenizer/weights and the required environment; outputs embedding effects |
| PRnet | Fixed official-resource reference evaluation in `scripts/prnet_reference_case.py`; historical scripts are retained separately | Accepts only the explicitly fixed reference resources. An executed reference case does not establish compatibility with arbitrary user baselines; unknown training overlap still precludes independent-validation claims |
| chemCPA, UniPert-G2CP | Historical adaptation scripts under `examples/lung_cancer/` | Verify and adapt paths, inputs, environments and weights; the presence of a historical script does not establish local executability |
| GEARS, UniCure, DrugReflector | Respective workflow references and code snippets | Prepare task-specific data/resources and implement/validate an adapter; these are not yet unified one-command entry points |

Read the [Capability registry](references/model-capabilities.md) to select a model, then [Resources and execution entry points](references/model-setup.md) for the chosen route. Treat historical paths in environment notes as troubleshooting references, not evidence of installation on the current machine. Isolate backend environments; do not force old dependencies into the main environment.

## 3. Compute results while preserving their original meaning

- **Observed-response walkthrough:** Compute each contrast as the source treatment profile minus its specified control. Preserve the source-processed scale and cross-plate flags. Do not describe these contrasts as predictions, longitudinal single-cell tracking or model validation.
- **Kang donor-paired walkthrough:** Align by sample and barcode, preserving unique gene IDs. Aggregate raw counts by donor/condition/cell label, explicitly specify the all-gene CPM denominator and pseudocount, compute within-donor contrasts and combine donors with equal weight. Do not treat cell counts as independent replicates or fill missing pairs with zero responses.
- **CellOracle:** Set KO to 0. For OE, require a fixed value or quantile on the internal `imputed_count` scale, with its rationale; report cells whose baseline exceeds that setting and is therefore reduced. Projections of randomized expression changes are technical controls. Do not interpret the vector difference between original and randomized projections as a specific signal.
- **Geneformer:** `delete` removes the target token; `overexpress` changes the rank encoding. The current example does not support `inhibit`/`activate`. Do not translate embedding changes into expression fold changes, differential expression or drug effects. Set the script's confirmation parameters only after verifying the provenance of the complete raw transcriptome.
- **GEARS:** Require training data that match the target background and perturbation type. Training on KO/CRISPRi does not establish support for arbitrary OE.
- **Compound screening:** External baselines for PRnet/chemCPA must match the weights' gene order, scale, covariates and training domain. Record patient-sample analyses as OOD exploration. UniPert-G2CP uses its bundled controls; the current invocation does not support arbitrary substitution with a user baseline or addition of doses. Preserve DrugReflector's native ranking/category definitions.
- Treat models without an actual entry point as unadapted until their sources, input contracts and execution evidence are established. A model name in historical materials is not a current capability. Perform molecular docking only when the user has selected compounds and proteins and explicitly included docking in the task.

Before execution, record effective settings, selection rationale, the actual interpreter, code/model versions, weights/priors, input hashes, parameters, randomness and training domain. Track each condition separately. Retain errors for failed conditions and artifacts for completed conditions without overwriting historical results.

## 4. Save complete results before checking and selecting them

For observed-response walkthroughs, first save complete provenance and observed contrasts. For model analyses, first save all predictions, corresponding baselines, responses, the gene axis and condition indices; only then derive top-result tables, scores and figures. Join rankings and responses by stable compound/condition IDs, not by row positions after sorting. If historical full results are missing, identify unrecoverable items; do not fabricate them from figures or top-result tables.

Retain the `expression`, `network`, `state_embedding`, `ranking` or `docking` outputs the backend actually supports. Record conditions, units, backgrounds, provenance, coverage and OOD status.

Keep the catalog stages `catalogued`, `data_downloaded`, `prepared`, `model_executed` and `validated` distinct. Assign stages from evidence; a script's existence, a successful download or a passed preflight does not automatically advance the stage. For observed-response walkthroughs, keep `model_status` at `not_run` and `independent_validation` at `not_assessed`. For model runs, record separately:

- Execution: `result_available`, `partial`, `no_prediction`, `failed`, `not_applicable`.
- Response: `response_status`, describing whether conditions produce distinguishable changes and the evidence for that check.
- Ranking: Record `condition_ranking_status` and `drug_ranking_status` separately. Reassess distinguishability after compound-level aggregation; retain screening `ranking_status` as the drug-level compatibility alias. If ranks are indistinguishable, record `unresolved` and stop candidate recommendations while retaining valid predictions and legitimate per-condition descriptive directions.
- Independent validation: When matching experiments or independent held-out validation are absent, record `validation_status: unvalidated` without replacing the execution status.

Block an affected condition when its input cannot be interpreted, output is absent, results are nonfinite or critical indices are missing. High correlations, tied rankings and a lack of independent validation do not automatically mean computation failed; passing technical checks does not establish drug sensitivity or efficacy.

When observations and predictions share a scale, use `scripts/evaluate_predictions.py`. Align stable sample/gene IDs; retain the zero-response reference and metrics weighted equally across the declared biological units. Check training/evaluation membership, background, scale and baseline. Nonoverlapping membership establishes a split check only within the supplied lists; it does not automatically establish independence from every training source. A leave-one-donor-out mean baseline is a cross-validation walkthrough, not independent accuracy evidence for CellOracle or PRnet.

## 5. Generate applicable figures and explanations

Before plotting, read [Downstream result requirements](references/downstream-results.md). Generate complementary figure sets from actual outputs: expression responses, state shifts, embedding effects or native rankings. Annotate units, baselines and source tables alongside the figures. Compute disease-direction scores only when a suitable disease reference is provided and gene spaces, expression platforms and experimental conditions are comparable. Otherwise, skip that scoring and preserve native outputs.

Save per-condition compound-screening results and full responses first. When expression output is available, deliver the top 30 changed genes for each compound/condition, preserving direction and stable IDs. Reversal-direction categories describe predicted transcriptional responses only. Retain an "undetermined" classification and reason for invalid or unscored conditions.

For supported Kang, CellOracle and PRnet runs, use `scripts/explain_result.py` to generate an interpretation in a new directory. The interpretation tool reads existing results without rerunning the model. Check actual statuses and required tables before extracting key values. Explain positive and negative changes, metric definitions, independent replicate units, quality issues and next steps. For an unrecognized contract, report specific missing requirements instead of inferring success from the presence of files.

For model routes, record each figure's generated, skipped or failed status in `figures/figure_manifest.csv`. HT115 and Kang observed-response walkthroughs use the root-level `figure_manifest.json` their scripts actually produce; do not fabricate a model figure manifest. Missing optional figures do not change successful prediction status. If a figure fails, regenerate only the affected figure without rerunning a completed model. Keep experimental perturbation-validation figures separate from simulation figures. Provide p-values, error bars, viability and IC50 only when corresponding data and methods exist.

## 6. Deliver an auditable run package

Create a new output directory. For observed-response walkthroughs, retain the script's actual `report.md`, `provenance.json`, `qc.json`, `figure_manifest.json`, complete tables and raw arrays; do not fabricate model-inference records. For model analyses, use a new `<analysis_dir>/results/<run_id>/` and save `manifest.json`, `provenance.json`, `raw/`, `tables/`, `figures/`, `validation.json`, `errors.jsonl` and `report.md`. Supplement fields the script does not record automatically while preserving the original records.

Start the report with what was done, which conditions completed, the baseline used and what the results support. Then provide key values, source tables/figures, exceptions and next steps. Clearly distinguish historical review, current execution, technical checks and independent validation. Do not infer clinical efficacy, disease mechanisms, causality or target confirmation directly from prediction scores.

## References to load as needed

- [First run](references/first-run.md): Agent installation, files and research tasks, result delivery, optional public cases and technical reproduction.
- [User data](references/user-data.md): Table/H5AD preparation, scale and ID checks, and subsequent model inputs.
- [Prediction evaluation](references/prediction-evaluation.md): Same-scale comparisons, simple baselines, biological-unit aggregation and split audits.
- [Result interpretation](references/result-reading.md): Supported result contracts, key values and source tables, limitations and next actions.
- [Case catalog](cases/README.md), [catalog.json](cases/catalog.json): Case sources, resources, actual stages and limitations.
- [Execution playbook](references/execution-playbook.md): Default settings, one consolidated question round, run records and failure handling.
- [Input contracts](references/input-contracts.md), [Capability registry](references/model-capabilities.md): Input requirements and model scope.
- [Methodology and independent maintenance scope](docs/methodology-and-scope.md): Observation/prediction scales, experimental units, evaluation leakage and scientific attribution; historical demonstration conclusions do not establish new analyses.
- [Resources and execution entry points](references/model-setup.md), [Environment notes](references/backend-environments.md): Verify resources and dependencies after selecting a backend.
- [Parameterized KO/OE examples](examples/ko_oe/README.md): Actual CellOracle/Geneformer CLIs and outputs.
- [GEARS](references/gears-workflow.md), [UniCure](references/unicure-workflow.md), [DrugReflector](references/drugreflector-workflow.md): Research routes that require task-specific adaptation.
- [Downstream result requirements](references/downstream-results.md): Plotting, scoring, condition indices and scientific interpretation boundaries.
- [Historical archive](archive/aivc-587579e7/reproduction-report.md), [Corrections](docs/audit-remediation.md): Read only when reviewing earlier research; these do not constitute execution evidence for a new case.
- [Contribution guidelines](CONTRIBUTING.md), [Source notices](THIRD_PARTY_NOTICES.md): Maintain individual cases or adapters while preserving authorship and resource licenses.
- [Preflight and troubleshooting](docs/troubleshooting.md): Lightweight preflight requests, statuses and next steps for common problems.

Make targeted changes when maintaining this repository; do not reinitialize the Skill. Before distribution, check documentation links, relevant behavior tests and the file list produced by `scripts/package_skill.py`. Exclude model weights, user data and temporary run artifacts from the distribution package.
