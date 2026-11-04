document.addEventListener("submit", (event) => {
  const form = event.target;
  const submitter = event.submitter;
  const message = submitter?.dataset.confirm || form.dataset.confirm;
  if (message && !window.confirm(message)) {
    event.preventDefault();
    return;
  }

  if (submitter?.name === "action" && submitter.value === "reject") {
    const comment = form.querySelector('textarea[name="comment"]');
    if (!comment?.value.trim()) {
      event.preventDefault();
      comment?.focus();
      window.alert("반려 사유를 입력하세요.");
    }
  }
});

document.querySelectorAll("[data-delete-confirmation]").forEach((form) => {
  const expected = form.dataset.deleteConfirmation;
  const input = form.querySelector("[data-delete-confirmation-input]");
  const submit = form.querySelector("[data-delete-submit]");

  const update = () => {
    const matches = input?.value.trim() === expected;
    if (submit) submit.disabled = !matches;
    input?.classList.toggle("is-invalid", Boolean(input?.value) && !matches);
  };

  input?.addEventListener("input", update);
  form.addEventListener("reset", () => window.setTimeout(update, 0));
  form.closest(".modal")?.addEventListener("hidden.bs.modal", () => {
    form.reset();
    input?.classList.remove("is-invalid");
  });
  form.addEventListener("submit", (event) => {
    if (input?.value.trim() !== expected) {
      event.preventDefault();
      input?.classList.add("is-invalid");
      input?.focus();
    }
  });
  update();
});
