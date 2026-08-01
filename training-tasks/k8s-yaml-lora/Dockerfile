FROM pytorch/pytorch:2.5.1-cuda12.1-cudnn9-runtime

WORKDIR /app

# kubeconform - schema validator used by eval.py. No live cluster needed.
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/* \
    && curl -sL https://github.com/yannh/kubeconform/releases/download/v0.8.0/kubeconform-linux-amd64.tar.gz \
    | tar xz -C /usr/local/bin kubeconform

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# train.py/eval.py/data/ are deliberately NOT copied here - the orchestrator's
# git-clone init container supplies the current repo checkout at job start, so
# code/data changes don't require rebuilding this image. This image only needs
# rebuilding when requirements.txt changes.
