from io import BytesIO

from PIL import Image


def image(fmt, color):
    buffer = BytesIO()
    Image.new("RGB", (96, 64), color).save(buffer, fmt)
    return buffer.getvalue()


def test_batch_upload_validates_all_images_before_publishing(client, admin, app):
    path = "/api/v1/references/batch"
    first = ("files", ("van__front.jpg", image("JPEG", "red"), "image/jpeg"))
    second = ("files", ("van__back.webp", image("WEBP", "blue"), "image/webp"))
    result = client.post(path, headers=admin, files=[first, second])
    assert result.status_code == 201, result.text
    items = result.json()["items"]
    assert [ref["filename"] for ref in items] == ["van__front.jpg", "van__back.webp"]
    assert all(client.get(f"/api/v1/references/{ref['id']}", headers=admin).content.startswith(b"\x89PNG") for ref in items)
    bad = client.post(path, headers=admin, files=[first, ("files", ("bad.png", b"x", "image/png"))])
    assert bad.status_code == 422
    assert len(list((app.state.storage.root / "references").glob("ref_*.png"))) == 2


def test_unmatted_pixal_job_requires_worker_with_preparation(client, admin, make_worker):
    ref = client.post("/api/v1/references", headers=admin,
                      files={"file": ("truck.jpg", image("JPEG", "silver"), "image/jpeg")}).json()["id"]
    old = make_worker(kind="nvidia", features=("engine.pixal3d-sv",))
    job = {"name": "Truck", "job_type": "experimental.reconstruct",
           "params": {"category": "vehicle", "engine": "pixal3d-sv", "references": {"front": ref}}}
    assert client.post("/api/v1/jobs", headers=admin, json=job | {"worker_id": old.id}).status_code == 422
    response = client.post("/api/v1/jobs", headers=admin, json=job)
    assert response.status_code == 201, response.text
    assert "engine.reference-prep" in response.json()["requirements"]["features"]
