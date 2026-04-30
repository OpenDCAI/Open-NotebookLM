from src.materials.image_generator import ImageGenerator


def test_image_generator_defaults_to_lower_resolution_and_longer_timeout():
    defaults = ImageGenerator.generate_image.__kwdefaults__

    assert defaults["resolution"] == "1K"
    assert defaults["timeout"] == 600


def test_presentagent_gateway_with_gemini_named_model_uses_generate_content():
    generator = ImageGenerator(
        api_key="key",
        api_base="http://123.129.219.111:3000/v1",
        model="gemini-3.1-flash-image-preview",
    )

    request_type, url, payload = generator._build_generation_request(
        prompt="draw a chart illustration",
        aspect_ratio="16:9",
        resolution="2K",
        quality="standard",
        style="vivid",
        response_format="b64_json",
    )

    assert request_type == "gemini_native"
    assert url == "http://123.129.219.111:3000/v1beta/models/gemini-3.1-flash-image-preview:generateContent"
    assert payload["generationConfig"]["responseModalities"] == ["IMAGE"]


def test_google_native_gemini_endpoint_uses_generate_content():
    generator = ImageGenerator(
        api_key="key",
        api_base="https://generativelanguage.googleapis.com",
        model="gemini-3.1-flash-image-preview",
    )

    request_type, url, _payload = generator._build_generation_request(
        prompt="draw a chart illustration",
        aspect_ratio="16:9",
        resolution="2K",
        quality="standard",
        style="vivid",
        response_format="b64_json",
    )

    assert request_type == "gemini_native"
    assert url == "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-image-preview:generateContent"


def test_comfly_gateway_keeps_openai_images_api_for_gemini_named_model():
    generator = ImageGenerator(
        api_key="key",
        api_base="https://api.comfly.chat/v1",
        model="gemini-3.1-flash-image-preview",
    )

    request_type, url, payload = generator._build_generation_request(
        prompt="draw a chart illustration",
        aspect_ratio="16:9",
        resolution="2K",
        quality="standard",
        style="vivid",
        response_format="b64_json",
    )

    assert request_type == "openai_images"
    assert url == "https://api.comfly.chat/v1/images/generations"
    assert payload["model"] == "nano-banana-2-2k"
