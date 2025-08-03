#! /bin/bash
set -e

SCRIPT_DIR=$(dirname ${BASH_SOURCE[0]})

if ! [[ -x $(command -v pyenv) ]]; then
    echo "Pyenv must be installed."
    exit 1
fi

pyenv virtualenv --version

if [[ $(pyenv versions | grep 3.9.19 | wc -l) == "0" ]]; then
    pyenv install 3.13.5
fi

if [[ $(pyenv versions | grep xbot-3.9 | wc -l) == "0" ]]; then
    pyenv virtualenv 3.13.5 open-3.13
fi

eval "$(pyenv init --path)"
eval "$(pyenv init -)"
eval "$(pyenv virtualenv-init -)"

pyenv activate open-3.13

pip install -r $SCRIPT_DIR/requirements.txt

pre-commit install
