# Generalization eval set (NOT training data)

14 bug shapes that do **not** appear anywhere in `manual_examples/` --
match-case bodies, `__slots__` defaults, dotted-submodule imports, a class
shadowed by a same-named function, async function/redefinition variants,
generator/async unused-variable cases, a `{`/`]` bracket mismatch, missing
colons on decorated and `async def` signatures, a three-element assert
tuple, and an undefined name used as a class-definition keyword argument.

This directory is deliberately **excluded from training**: never point
`build_manual_dataset.py` or `train_lora.py` at it. Its only purpose is to
answer the question `eval_model.py` against `manual_examples/` cannot --
whether the fine-tune generalized past the specific shapes it trained on,
or just memorized them.

Usage, once your model is in place (`INVARIANTSMITH_MODEL_FILE` set,
`llama-cpp-python` installed):

```
python data_pipeline/eval_model.py --examples-dir data_pipeline/generalization_examples
```

Every example here has already been validated with:

```
python data_pipeline/build_manual_dataset.py --examples-dir data_pipeline/generalization_examples --out-dir /tmp/genout
```

(14 accepted, 0 rejected) -- confirming each one trips exactly the
intended detector error and that `fixed.py` verifies against the same
`_verify_fix()` path production uses. That only proves the *examples* are
well-formed, though -- it says nothing about your model. A weak pass rate
here (compared to `manual_examples/`) is the actual signal you're looking
for.
