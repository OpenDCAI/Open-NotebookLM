from pathlib import Path

from PIL import Image
from pptx.util import Inches

from src.coder import pptx_library as lib
from src.coder.qwen_recipe_audit import audit_pptx


def test_audit_pptx_reports_text_overlaps(tmp_path):
    output_path = tmp_path / "overlap.pptx"
    prs = lib.create_presentation()
    slide = lib.add_blank_slide(prs)
    lib.add_textbox(slide, "A", 1.0, 1.0, 3.0, 1.0)
    lib.add_textbox(slide, "B", 2.0, 1.2, 3.0, 1.0)
    prs.save(output_path)

    audit = audit_pptx(str(output_path))

    assert audit["status"] == "fail"
    assert audit["slide_count"] == 1
    assert audit["text_overlaps"]


def test_audit_pptx_reports_out_of_bounds_shapes(tmp_path):
    output_path = tmp_path / "bounds.pptx"
    prs = lib.create_presentation()
    slide = lib.add_blank_slide(prs)
    lib.add_textbox(slide, "Too wide", 12.8, 1.0, 1.0, 0.6)
    prs.save(output_path)

    audit = audit_pptx(str(output_path))

    assert audit["status"] == "fail"
    assert audit["out_of_bounds"]


def test_audit_pptx_passes_clean_slide(tmp_path):
    output_path = tmp_path / "clean.pptx"
    prs = lib.create_presentation()
    slide = lib.add_blank_slide(prs)
    lib.add_textbox(slide, "A", 1.0, 1.0, 3.0, 0.8)
    lib.add_textbox(slide, "B", 1.0, 2.0, 3.0, 0.8)
    prs.save(output_path)

    audit = audit_pptx(str(output_path))

    assert audit["status"] == "pass"
    assert audit["text_overlaps"] == []
    assert audit["out_of_bounds"] == []


def test_audit_pptx_reports_image_aspect_distortion(tmp_path):
    image_path = tmp_path / "wide.png"
    output_path = tmp_path / "stretched.pptx"
    Image.new("RGB", (1600, 900), color=(20, 20, 20)).save(image_path)
    prs = lib.create_presentation()
    slide = lib.add_blank_slide(prs)
    slide.shapes.add_picture(str(image_path), Inches(0.5), Inches(1.0), Inches(10.0), Inches(1.5))
    prs.save(output_path)

    audit = audit_pptx(str(output_path))

    assert audit["status"] == "fail"
    assert audit["image_aspect_distortions"]
    assert audit["image_aspect_distortions"][0]["native_aspect"] == round(1600 / 900, 3)


def test_audit_pptx_reports_duplicate_visible_text(tmp_path):
    output_path = tmp_path / "duplicate_text.pptx"
    prs = lib.create_presentation()
    slide = lib.add_blank_slide(prs)
    repeated = "基于50位领域专家的评估，系统获得64%正面标签。"
    lib.add_textbox(slide, repeated, 1.0, 1.0, 4.0, 0.8)
    lib.add_textbox(slide, f"核心结论：{repeated}", 6.0, 1.0, 4.0, 0.8)
    prs.save(output_path)

    audit = audit_pptx(str(output_path))

    assert audit["status"] == "fail"
    assert audit["duplicate_text_warnings"]
    assert "50位领域专家" in audit["duplicate_text_warnings"][0]["text"]


def test_audit_pptx_reports_text_that_cannot_fit_its_own_box(tmp_path):
    output_path = tmp_path / "overflow.pptx"
    prs = lib.create_presentation()
    slide = lib.add_blank_slide(prs)
    lib.add_textbox(
        slide,
        "Step 1 — Expert reviews agent response in production UI and provides detailed corrections.",
        1.0,
        1.0,
        0.8,
        0.08,
        font_size=14,
        fit=False,
    )
    prs.save(output_path)

    audit = audit_pptx(str(output_path))

    assert audit["status"] == "fail"
    assert audit["text_box_overflows"]
    assert audit["text_box_overflows"][0]["estimated_required_height"] > audit["text_box_overflows"][0]["box_height"]


def test_audit_pptx_reports_table_cell_text_overflow(tmp_path):
    output_path = tmp_path / "table_cell_overflow.pptx"
    prs = lib.create_presentation()
    slide = lib.add_blank_slide(prs)
    lib.add_table(
        slide,
        [
            ["维度", "ClimSight", "MYCC"],
            ["气候投影模型", "单一模型", "多模型并支持农业规划专家工作流、跨区域对比、长期气候情景解释与专家审阅"],
            ["目标受众", "泛用户", "专家用户"],
        ],
        6.9,
        5.2,
        5.5,
        0.48,
    )
    prs.save(output_path)

    audit = audit_pptx(str(output_path))

    assert audit["status"] == "fail"
    assert audit["table_cell_overflows"]


def test_audit_pptx_reports_picture_text_overlaps(tmp_path):
    image_path = tmp_path / "wide.png"
    output_path = tmp_path / "picture_text_overlap.pptx"
    Image.new("RGB", (1600, 900), color=(20, 80, 120)).save(image_path)
    prs = lib.create_presentation()
    slide = lib.add_blank_slide(prs)
    lib.safe_add_picture(slide, str(image_path), 3.0, 2.0, 4.0, 2.2)
    lib.add_textbox(slide, "Overlapping note", 4.0, 2.4, 3.0, 0.6, font_size=16)
    prs.save(output_path)

    audit = audit_pptx(str(output_path))

    assert audit["status"] == "fail"
    assert audit["picture_text_overlaps"]
