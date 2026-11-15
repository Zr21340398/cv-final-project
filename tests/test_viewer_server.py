"""Exercise the viewer's portable manifest and access boundary."""

import importlib.util
import json
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[1] / "gso-viewer" / "server.py"
spec = importlib.util.spec_from_file_location("viewer_server", SERVER)
viewer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(viewer)


def test_catalog_and_selected_reference(tmp_path):
    data_root = tmp_path / "data"
    experiment = data_root / "experiment"
    reference = data_root / "references" / "cup.glb"
    generated = experiment / "variant" / "cup.glb"
    reference.parent.mkdir(parents=True)
    generated.parent.mkdir(parents=True)
    reference.write_bytes(b"reference")
    generated.write_bytes(b"result")
    dataset = {
        "id": "sample",
        "label": "Sample",
        "objects": [{"id": "cup", "reference": "../references/cup.glb"}],
        "variants": [{"id": "variant", "label": "Variant"}],
        "runs": [
            {"object": "cup", "variant": "variant", "seed": 42, "status": "completed",
             "models": {"asset": "variant/cup.glb"}},
            {"object": "cup", "variant": "variant", "seed": 123, "status": "pending", "models": {}},
        ],
    }
    service = viewer.Datasets(data_root)
    service.add(dataset, experiment)
    catalog = service.catalog()["datasets"][0]
    assert catalog["objects"][0]["reference"] is True
    assert catalog["runs"][0]["kinds"] == ["asset"]
    assert catalog["runs"][1]["kinds"] == []
    assert service.resolve("dataset=sample&object=cup&kind=reference") == reference.resolve()
    assert service.resolve("dataset=sample&object=cup&kind=asset&variant=variant&seed=42") == generated.resolve()
    with pytest.raises(FileNotFoundError):
        service.resolve("dataset=sample&object=cup&kind=asset&variant=variant&seed=123")


def test_reference_cannot_escape_data_root(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    external = tmp_path / "outside.glb"
    external.write_bytes(b"private")
    service = viewer.Datasets(allowed)
    service.add({"id": "sample", "objects": [{"id": "cup", "reference": "../outside.glb"}],
                 "variants": [], "runs": []}, allowed)
    assert service.catalog()["datasets"][0]["objects"][0]["reference"] is False
    with pytest.raises(ValueError, match="outside"):
        service.resolve("dataset=sample&object=cup&kind=reference")


def test_empty_data_can_be_used_without_preset(tmp_path):
    assert viewer.Datasets(tmp_path).catalog() == {"datasets": []}


def test_discover_multiple_experiments_with_same_internal_id_and_refresh(tmp_path):
    def make_experiment(name, object_id):
        folder = tmp_path / name / "results" / "same-result-name"
        folder.mkdir(parents=True)
        model = folder / "asset.glb"
        model.write_bytes(b"model")
        data = {"schema_version": 1, "id": "same-result-name", "objects": [{"id": object_id}],
                "variants": [{"id": "baseline", "label": "baseline"}],
                "runs": [{"object": object_id, "variant": "baseline", "seed": 42,
                          "models": {"asset": "asset.glb"}}]}
        (folder / "viewer-manifest.json").write_text(json.dumps(data), encoding="utf-8")

    make_experiment("experiment-a", "cup")
    service = viewer.DiscoveredDatasets(tmp_path)
    assert service.refresh() == []
    first = service.catalog()["datasets"]
    assert len(first) == 1
    assert first[0]["label"] == "experiment-a / same-result-name"
    make_experiment("experiment-b", "chair")
    assert service.refresh() == []
    datasets = service.catalog()["datasets"]
    assert len(datasets) == 2
    assert len({item["id"] for item in datasets}) == 2
    assert {item["objects"][0]["id"] for item in datasets} == {"cup", "chair"}
    assert first[0]["id"] in {item["id"] for item in datasets}


def test_bad_manifest_does_not_hide_other_experiments(tmp_path):
    results = tmp_path / "results"
    good, bad = results / "good", results / "bad"
    good.mkdir(parents=True)
    bad.mkdir()
    (good / "viewer-manifest.json").write_text(
        json.dumps({"schema_version": 1, "id": "good", "objects": [], "variants": [], "runs": []}),
        encoding="utf-8",
    )
    (bad / "viewer-manifest.json").write_text("{not json", encoding="utf-8")
    service = viewer.DiscoveredDatasets(tmp_path)
    problems = service.refresh()
    assert len(problems) == 1
    assert [x["label"] for x in service.catalog()["datasets"]] == ["good"]


def test_run_input_uses_its_own_image_and_never_falls_back_on_explicit_null(tmp_path):
    experiment = tmp_path / "exp"
    experiment.mkdir()
    model = experiment / "asset.glb"
    model.write_bytes(b"model")
    image = experiment / "input.png"
    image.write_bytes(b"correct image")
    service = viewer.Datasets(tmp_path)
    service.add({"id": "a", "objects": [{"id": "cup", "input": "input.png"}], "variants": [],
                 "runs": [{"object": "cup", "variant": "old", "seed": 1, "models": {"asset": "asset.glb"}},
                          {"object": "cup", "variant": "new", "seed": 1, "input": None,
                           "models": {"asset": "asset.glb"}}]}, experiment)
    assert service.resolve("dataset=a&object=cup&variant=old&seed=1", image=True) == image.resolve()
    with pytest.raises(FileNotFoundError):
        service.resolve("dataset=a&object=cup&variant=new&seed=1", image=True)


def test_custom_types_arbitrary_paths_and_seedless_runs(tmp_path):
    folder = tmp_path / "any-layout"
    folder.mkdir()
    raw = folder / "before-any-name.glb"
    clean = folder / "after-any-name.glb"
    raw.write_bytes(b"raw")
    clean.write_bytes(b"clean")
    service = viewer.Datasets(tmp_path)
    service.add({"id": "custom", "objects": [{"id": "speaker"}],
                 "model_types": {"paint_before": "Before", "paint_after": "After"},
                 "variants": [{"id": "cleanup", "label": "Cleanup"}],
                 "runs": [{"object": "speaker", "variant": "cleanup", "input": None,
                           "models": {"paint_before": "any-layout/before-any-name.glb",
                                      "paint_after": "any-layout/after-any-name.glb"}}]}, tmp_path)
    catalog = service.catalog()["datasets"][0]
    assert catalog["seeds"] == ["None"]
    assert catalog["kinds"] == [{"id": "paint_before", "label": "Before"},
                                {"id": "paint_after", "label": "After"}]
    query = "dataset=custom&object=speaker&variant=cleanup&seed=None&kind="
    assert service.resolve(query + "paint_before") == raw.resolve()
    assert service.resolve(query + "paint_after") == clean.resolve()
    with pytest.raises(FileNotFoundError):
        service.resolve(query + "not-declared")


def test_modular_experiment_references_shared_dataset(tmp_path):
    batch = tmp_path / "experiments/new-run/results"
    batch.mkdir(parents=True)
    data = tmp_path / "datasets/gso-v1"
    data.mkdir(parents=True)
    (data / "ref.glb").write_bytes(b"reference")
    (batch / "output.glb").write_bytes(b"generated")
    manifest = {"schema_version": 1, "id": "new-run",
                "objects": [{"id": "cup", "reference": "../../../datasets/gso-v1/ref.glb"}],
                "variants": [{"id": "trellis2"}],
                "runs": [{"object": "cup", "variant": "trellis2", "seed": 42,
                          "models": {"asset": "output.glb"}}]}
    (batch / "viewer-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    service = viewer.DiscoveredDatasets(tmp_path)
    assert service.refresh() == []
    item = service.catalog()["datasets"][0]
    assert item["objects"][0]["reference"]
    assert service.resolve(f"dataset={item['id']}&object=cup&kind=reference") == data / "ref.glb"
