"""UI adapter contract and two concrete implementations.

The elicitor depends only on the `UIAdapter` ABC so it can be driven
from any front-end (CLI for dev/tests, Streamlit for the demo, or a
mock for unit tests).

A question is a dict matching `QuestionTemplate` from
question_templates.py. `ask` returns a `(display_label, internal_value)`
tuple. If the user chose a pre-defined option, `internal_value` is the
corresponding entry in `option_values`. If they typed a free-text
answer via the "Other" fallback, both members of the tuple are the
typed text — the elicitor detects this by observing that
`internal_value` is not in `option_values`.
"""

from abc import ABC, abstractmethod
from typing import Callable

OTHER_LABEL = "Other (specify)"


class UIAdapter(ABC):
    @abstractmethod
    def ask(self, question: dict) -> tuple[str, str]:
        """Show a question and return `(display_label, internal_value)`."""
        ...


class CLIAdapter(UIAdapter):
    """Reads from stdin; used for development and integration tests."""

    def __init__(
        self,
        input_fn: Callable[[str], str] = input,
        output_fn: Callable[[str], None] = print,
    ):
        self._input = input_fn
        self._output = output_fn

    def ask(self, question: dict) -> tuple[str, str]:
        labels = list(question["options"])
        allow_other = bool(question.get("allow_other", False))
        if allow_other:
            labels.append(OTHER_LABEL)

        self._output("")
        self._output(question["text"])
        for i, label in enumerate(labels, start=1):
            self._output(f"  {i}. {label}")

        idx = self._read_index(len(labels))
        choice = labels[idx - 1]

        if allow_other and choice == OTHER_LABEL:
            text = self._read_nonempty("Please specify: ")
            return (text, text)

        return (choice, question["option_values"][idx - 1])

    def _read_index(self, n: int) -> int:
        while True:
            raw = self._input("Enter number: ").strip()
            try:
                idx = int(raw)
            except ValueError:
                self._output("Please enter a number.")
                continue
            if 1 <= idx <= n:
                return idx
            self._output(f"Please enter a number between 1 and {n}.")

    def _read_nonempty(self, prompt: str) -> str:
        while True:
            text = self._input(prompt).strip()
            if text:
                return text
            self._output("Answer cannot be empty.")


class StreamlitAdapter(UIAdapter):
    """Streamlit-backed adapter for the demo UI.

    Streamlit re-runs the script on every interaction, so answers are
    persisted to `st.session_state` and `st.stop()` halts execution
    until the user submits. Instantiate one adapter per elicitation
    call (i.e., per claim) so the internal question counter resets.
    """

    def __init__(self, key_prefix: str = "elicit"):
        self.key_prefix = key_prefix
        self._counter = 0

    def ask(self, question: dict) -> tuple[str, str]:
        import streamlit as st  # imported lazily so tests don't require streamlit

        qid = f"{self.key_prefix}_q{self._counter}"
        self._counter += 1
        answer_key = f"{qid}_answer"

        if answer_key in st.session_state:
            return st.session_state[answer_key]

        labels = list(question["options"])
        allow_other = bool(question.get("allow_other", False))
        if allow_other:
            labels.append(OTHER_LABEL)

        choice = st.radio(question["text"], labels, key=f"{qid}_radio")
        other_text = ""
        if allow_other and choice == OTHER_LABEL:
            other_text = st.text_input("Please specify:", key=f"{qid}_other")

        if st.button("Submit", key=f"{qid}_submit"):
            if choice == OTHER_LABEL:
                text = other_text.strip()
                if not text:
                    st.warning("Please type an answer before submitting.")
                    st.stop()
                result = (text, text)
            else:
                i = question["options"].index(choice)
                result = (choice, question["option_values"][i])
            st.session_state[answer_key] = result
            return result

        st.stop()
        raise RuntimeError("unreachable: st.stop() halts execution")
