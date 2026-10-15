"use strict";

const form = document.querySelector(".editor-grid");
const editor = document.querySelector("#configuration");
const configId = document.querySelector("#config-id");
const templates = document.querySelector("#template");
const description = document.querySelector("#template-description");
const status = document.querySelector("#editor-status");
const output = document.querySelector("#configure-url");
const lengthNote = document.querySelector("#link-length");
const validateButton = document.querySelector("#validate");
const copyButton = document.querySelector("#copy-link");
const openLink = document.querySelector("#open-link");
let revision = 0;
let pending = null;

function message(text, kind = "neutral") {
  status.textContent = text;
  status.dataset.kind = kind;
}

function changed() {
  revision += 1;
  pending?.abort();
  pending = null;
  validateButton.disabled = false;
  output.value = "";
  copyButton.disabled = true;
  openLink.removeAttribute("href");
  openLink.setAttribute("aria-disabled", "true");
  openLink.tabIndex = -1;
  lengthNote.textContent = "Validate your changes to generate a fresh link.";
  message("Configuration changed. Validate to update your link.");
}

function parseJson() {
  try {
    return JSON.parse(editor.value);
  } catch (error) {
    throw new Error(`Invalid JSON: ${error.message}`);
  }
}

editor.addEventListener("input", changed);
configId.addEventListener("input", changed);
templates.addEventListener("change", () => {
  const option = templates.selectedOptions[0];
  editor.value = JSON.stringify(JSON.parse(option.dataset.configuration), null, 2);
  description.textContent = option.dataset.description;
  changed();
  message("Template loaded. Edit the JSON or validate to get your link.");
});

document.querySelector("#new-id").addEventListener("click", () => {
  configId.value = crypto.randomUUID();
  changed();
});

document.querySelector("#format-json").addEventListener("click", () => {
  changed();
  try {
    editor.value = JSON.stringify(parseJson(), null, 2);
    message("JSON formatted. Validate to get your link.");
  } catch (error) {
    message(error.message, "error");
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  changed();
  const thisRevision = revision;
  try {
    const configuration = parseJson();
    const controller = new AbortController();
    pending = controller;
    validateButton.disabled = true;
    message("Checking your configuration…");
    const response = await fetch("/editor", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config_id: configId.value, configuration }),
      signal: controller.signal,
    });
    const result = await response.json();
    if (thisRevision !== revision) return;
    if (!response.ok || !result.valid) {
      throw new Error(result.error || "Couldn't validate the configuration. Please try again.");
    }
    const url = new URL(result.url, window.location.origin).href;
    output.value = url;
    lengthNote.textContent = `${url.length.toLocaleString()} characters · ${result.request_line_bytes.toLocaleString()} of ${result.max_request_line_bytes.toLocaleString()} request-line bytes`;
    if (result.request_line_bytes > result.max_request_line_bytes) {
      message("Valid configuration, but this link is too long for the server. Shorten the JSON or use JSON POST instead.", "warning");
      return;
    }
    copyButton.disabled = false;
    openLink.href = url;
    openLink.setAttribute("aria-disabled", "false");
    openLink.tabIndex = 0;
    message("Valid configuration. Your link is ready to copy or open.", "success");
  } catch (error) {
    if (error.name !== "AbortError" && thisRevision === revision) {
      message(error instanceof TypeError ? "Couldn't reach the server. Please try again." : error.message, "error");
    }
  } finally {
    if (thisRevision === revision) {
      pending = null;
      validateButton.disabled = false;
    }
  }
});

copyButton.addEventListener("click", async () => {
  const thisRevision = revision;
  try {
    await navigator.clipboard.writeText(output.value);
    if (thisRevision === revision) message("Link copied. Paste it into your browser or test.", "success");
  } catch {
    if (thisRevision !== revision) return;
    output.focus();
    output.select();
    message("The link is selected. Press Ctrl+C or ⌘C to copy it.");
  }
});
