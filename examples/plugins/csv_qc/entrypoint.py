"""Real, small CSV input QC example. No network, LLM, model or biological prediction."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path

MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_VALUES = 2_000_000
MAX_GENES = 20_000
MAX_CELLS = 100_000


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def analyze(request, output):
    source = Path(request["input_csv"])
    if not source.is_absolute():
        raise ValueError("input_csv 必须是绝对路径")
    source = source.resolve(strict=True)
    if not source.is_file() or source.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("输入必须是小于等于 64 MiB 的普通 UTF-8 CSV 文件")
    fingerprint = sha256(source)
    scale = request.get("input_scale", "unknown")
    cell_ids, total, nonzero, empty_cells = set(), Decimal(0), 0, 0
    with localcontext() as context, source.open(encoding="utf-8-sig", newline="") as stream:
        # Bounded decimal inputs + 2M entries fit this precision without float rounding.
        context.prec = 300
        rows = csv.reader(stream, strict=True)
        header = next(rows, [])
        if not header or header[0] != "cell_id" or not 1 <= len(header) - 1 <= MAX_GENES:
            raise ValueError("表头第一列必须是 cell_id，后续应为 1–20,000 个基因")
        genes = header[1:]
        if any(not gene.strip() or "\0" in gene for gene in genes) or len(set(genes)) != len(genes):
            raise ValueError("基因列名必须非空且唯一")
        gene_nonzero = [0] * len(genes)
        for row_number, row in enumerate(rows, 2):
            if len(row) != len(header) or not row[0].strip() or "\0" in row[0] or row[0] in cell_ids:
                raise ValueError(f"第 {row_number} 行的列数、cell_id 或唯一性检查失败")
            cell_ids.add(row[0])
            if len(cell_ids) > MAX_CELLS or len(cell_ids) * len(genes) > MAX_VALUES:
                raise ValueError("教学插件上限：100,000 个细胞、2,000,000 个表达数值")
            values = []
            for column, raw in enumerate(row[1:]):
                if len(raw) > 128:
                    raise ValueError(f"第 {row_number} 行的数值文本过长")
                value = Decimal(raw)
                if not value.is_finite() or value < 0:
                    raise ValueError(f"第 {row_number} 行包含非有限或负值；本例只接受非负表达矩阵")
                parts = value.as_tuple()
                if len(parts.digits) > 50 or not -100 <= parts.exponent <= 100:
                    raise ValueError(f"第 {row_number} 行的数值精度或数量级超出教学插件范围")
                if scale == "raw_counts" and value != value.to_integral_value():
                    raise ValueError(f"第 {row_number} 行含小数，与用户声明的 raw_counts 不一致")
                values.append(value)
                if value:
                    nonzero += 1
                    gene_nonzero[column] += 1
            subtotal = sum(values, Decimal(0))
            total += subtotal
            if not total.is_finite():
                raise ValueError("表达总量超出有限数值范围")
            empty_cells += subtotal == 0
    if not cell_ids:
        raise ValueError("输入没有细胞数据行")
    if sha256(source) != fingerprint:
        raise ValueError("运行中输入文件发生变化，请对固定版本重新运行")

    cells, count = len(cell_ids), len(cell_ids) * len(genes)
    tables = output / "tables"
    tables.mkdir(parents=True, exist_ok=True)
    with (tables / "qc_metrics.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["metric", "value", "unit"])
        writer.writerows([
            ["cell_count", cells, "cells"], ["gene_count", len(genes), "genes"],
            ["matrix_entries", count, "entries"], ["expression_total", format(total, "f"), "input_expression_units"],
            ["nonzero_entries", nonzero, "entries"], ["nonzero_fraction", format(nonzero / count, ".17g"), "fraction"],
            ["zero_expression_cells", empty_cells, "cells"],
        ])
    with (tables / "gene_detection.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["gene", "nonzero_cells", "detected_fraction"])
        writer.writerows((gene, detected, format(detected / cells, ".17g"))
                         for gene, detected in zip(genes, gene_nonzero))
    report = ("# CSV 表达数据基础检查（教学插件）\n\n"
              f"输入：{source}\n\nSHA-256：{fingerprint}\n\n用户声明的数据尺度：{scale}\n\n"
              f"共 {cells} 个细胞、{len(genes)} 个基因；非零比例 {nonzero / count:.6%}；"
              f"全零细胞 {empty_cells} 个。\n\n"
              "本插件只计算表格完整性和基础数值统计；不会判断细胞质量合格与否，"
              "没有执行基因干预、药物响应预测、归一化或独立生物学验证。"
              "这些统计不能替代细胞类型注释、线粒体比例、双细胞、批次和供体层面的专业质控。\n")
    (output / "report.md").write_text(report, encoding="utf-8")
    result = {"api_version": "0.1", "summary": f"完成 {cells} 个细胞、{len(genes)} 个基因的基础数值检查。",
              "artifacts": [{"type": "table", "path": "tables/qc_metrics.csv"},
                            {"type": "table", "path": "tables/gene_detection.csv"},
                            {"type": "report", "path": "report.md"}]}
    (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"stage": "completed", "cells": cells, "genes": len(genes),
                      "input_sha256": fingerprint, "python_version": sys.version}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    options = parser.parse_args()
    try:
        request = json.loads(options.request.read_text(encoding="utf-8"))
        analyze(request, options.output)
    except (OSError, ValueError, KeyError, OverflowError, InvalidOperation, csv.Error) as exc:
        print(f"CSV QC failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
