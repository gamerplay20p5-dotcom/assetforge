"""Generate the reference for a text reconstruction with local Z-Image-Turbo weights."""

import json
import sys
from pathlib import Path

import torch
from diffusers import ZImagePipeline


def main():
    models, request, output = map(Path, sys.argv[1:])
    params = json.loads(request.read_text(encoding="utf-8"))
    pipe = ZImagePipeline.from_pretrained(str(models), torch_dtype=torch.bfloat16, local_files_only=True).to("cuda")
    prompt = (params["prompt"] + "\nReference image for making one 3D asset. Show the entire subject "
              "from a front three-quarter view, centered on a plain background, evenly lit, without captions or props.")
    with torch.inference_mode():
        image = pipe(prompt=prompt, width=1024, height=1024, num_inference_steps=9, guidance_scale=0,
                     generator=torch.Generator(device="cuda").manual_seed(params["seed"])).images[0]
    image.save(output)


if __name__ == "__main__":
    main()
