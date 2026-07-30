import json
import os

WF_PATH = os.path.join(os.path.dirname(__file__), "..", "workflow_krea2carousel.json")


def _load():
    with open(WF_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_no_leaked_api_key():
    """The source workflow carried a GrokPromptNode with an api_key widget — that
    whole branch is dropped on import, so no key field can ever be committed."""
    with open(WF_PATH, encoding="utf-8") as f:
        raw = f.read()
    assert "sk-or-v1" not in raw
    assert "api_key" not in raw


def test_remaining_nodes_present():
    graph = _load()
    expected = {"1", "3", "4", "6", "9", "10", "28", "41", "91", "98", "109", "110", "111", "112"}
    assert set(graph.keys()) == expected


def test_grok_prompt_branch_and_comparer_dropped():
    """106/108 (Grok generator + its image batch loader) fed nothing, and 113
    (rgthree Image Comparer) is a UI-only node whose temp images would flood the
    gallery — none of them may come back."""
    graph = _load()
    for nid in ("72", "106", "108", "113"):
        assert nid not in graph
    classes = {n["class_type"] for n in graph.values()}
    assert "GrokPromptNode" not in classes
    assert "Image Comparer (rgthree)" not in classes
    assert "ResolutionSelector" not in classes


def test_no_load_image_node_pure_t2i():
    graph = _load()
    assert all(n["class_type"] != "LoadImage" for n in graph.values())


def test_latent_is_sized_by_plain_ints_not_a_resolution_node():
    graph = _load()
    assert graph["10"]["class_type"] == "EmptyLatentImage"
    for k in ("width", "height", "batch_size"):
        assert isinstance(graph["10"]["inputs"][k], int)


def test_prompt_nodes_have_no_dangling_links():
    graph = _load()
    assert isinstance(graph["6"]["inputs"]["text"], str)
    assert isinstance(graph["41"]["inputs"]["text"], str)


def test_character_lora_is_slot_1():
    """The source graph had the character in slot 3; the app's Power Lora Loader
    convention puts it in slot 1 with helpers after it."""
    graph = _load()
    assert "krea2_cristiana" in graph["28"]["inputs"]["lora_1"]["lora"]
    for slot in ("lora_2", "lora_3", "lora_4"):
        assert "krea2_cristiana" not in graph["28"]["inputs"][slot]["lora"]


def test_sampler_chain_wired_through_lora_and_model_sampling():
    graph = _load()
    assert graph["28"]["inputs"]["model"] == ["1", 0]
    assert graph["91"]["inputs"]["model"] == ["28", 0]
    assert graph["98"]["inputs"]["model"] == ["91", 0]
    assert graph["98"]["inputs"]["latent_image"] == ["10", 0]
    assert graph["3"]["inputs"]["samples"] == ["98", 0]


def test_camera_look_tail_chain_reaches_the_only_save_node():
    """VAEDecode -> Camera Look -> Renoise -> CRT Post -> Save, and exactly one
    save node so run() can't return duplicate/intermediate images."""
    graph = _load()
    assert graph["109"]["inputs"]["image"] == ["3", 0]
    assert graph["110"]["inputs"]["image"] == ["109", 0]
    assert graph["111"]["inputs"]["image"] == ["110", 0]
    assert graph["112"]["inputs"]["images"] == ["111", 0]
    savers = [nid for nid, n in graph.items() if "Save" in n["class_type"]]
    assert savers == ["112"]


def test_every_link_points_at_a_node_that_exists():
    graph = _load()
    for nid, node in graph.items():
        for k, v in node["inputs"].items():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str):
                assert v[0] in graph, f"{nid}.{k} -> missing node {v[0]}"
