from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ai_settings_model_fields_are_selects():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    for element_id in ("sResearchModel", "sWriterModel", "sReviewerModel"):
        assert f'<select id="{element_id}"></select>' in html


def test_main_app_populates_models_for_each_provider_and_role():
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    for provider in ("codex_local", "claude_local", "openai", "anthropic"):
        assert f"{provider}:" in js
    for provider_id, model_id in (
        ("#sResearchProvider", "#sResearchModel"),
        ("#sWriterProvider", "#sWriterModel"),
        ("#sReviewerProvider", "#sReviewerModel"),
    ):
        assert f"['{provider_id}','{model_id}']" in js
    assert "provider.onchange=()=>fillModelSelect(providerSelector,modelSelector)" in js
    assert "applyProviderModel('#sResearchProvider','#sResearchModel'" in js
    assert "applyProviderModel('#sWriterProvider','#sWriterModel'" in js
    assert "applyProviderModel('#sReviewerProvider','#sReviewerModel'" in js
