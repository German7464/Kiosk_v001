const eventFormPreview = document.querySelector("[data-event-form-preview]");
const formPreviewModal = document.querySelector("[data-form-preview-modal]");
const formPreviewModalMode = document.querySelector("[data-form-preview-modal-mode]");
const formPreviewModalCard = document.querySelector("[data-form-preview-modal-card]");
const formPreviewModalImage = document.querySelector("[data-form-preview-modal-image]");
const formPreviewModalTitle = document.querySelector("[data-form-preview-modal-title]");
const formPreviewModalDate = document.querySelector("[data-form-preview-modal-date]");
const formPreviewModalPlace = document.querySelector("[data-form-preview-modal-place]");
const formPreviewModalDescription = document.querySelector("[data-form-preview-modal-description]");
const closeFormPreview = document.querySelector("[data-close-form-preview]");
const previewFields = {
    title: document.querySelector("[data-event-preview-field='title']"),
    eventDate: document.querySelector("[data-event-preview-field='event_date']"),
    place: document.querySelector("[data-event-preview-field='place']"),
    shortDescription: document.querySelector("[data-event-preview-field='short_description']"),
    image: document.querySelector("[data-event-preview-field='image']"),
};
const previewTargets = {
    title: document.querySelectorAll("[data-form-preview-title]"),
    date: document.querySelectorAll("[data-form-preview-date]"),
    place: document.querySelectorAll("[data-form-preview-place]"),
    description: document.querySelectorAll("[data-form-preview-description]"),
    images: document.querySelectorAll("[data-form-preview-image]"),
};
let currentPreviewImage = "";

function previewValue(field, placeholder) {
    return field && field.value.trim() ? field.value.trim() : placeholder;
}

function setPreviewText(targets, text) {
    targets.forEach((target) => {
        target.textContent = text;
    });
}

function setPreviewImages(imageUrl) {
    currentPreviewImage = imageUrl || "";

    previewTargets.images.forEach((target) => {
        target.innerHTML = "";
        target.style.backgroundImage = "";

        if (!currentPreviewImage) {
            const placeholder = document.createElement("span");
            placeholder.textContent = eventFormPreview.dataset.imagePlaceholder;
            target.appendChild(placeholder);
            return;
        }

        const image = new Image();
        image.onload = () => {
            target.innerHTML = "";
            target.style.backgroundImage = `url("${currentPreviewImage}")`;
        };
        image.onerror = () => {
            const placeholder = document.createElement("span");
            target.innerHTML = "";
            target.style.backgroundImage = "";
            placeholder.textContent = eventFormPreview.dataset.imagePlaceholder;
            target.appendChild(placeholder);
        };
        image.src = currentPreviewImage;
    });
}

function updateEventFormPreview() {
    setPreviewText(previewTargets.title, previewValue(previewFields.title, eventFormPreview.dataset.titlePlaceholder));
    setPreviewText(previewTargets.date, previewValue(previewFields.eventDate, eventFormPreview.dataset.datePlaceholder));
    setPreviewText(previewTargets.place, previewValue(previewFields.place, eventFormPreview.dataset.placePlaceholder));
    setPreviewText(previewTargets.description, previewValue(previewFields.shortDescription, eventFormPreview.dataset.descriptionPlaceholder));
}

function setModalImage(imageUrl) {
    formPreviewModalImage.innerHTML = "";
    formPreviewModalImage.style.backgroundImage = "";

    if (!imageUrl) {
        const placeholder = document.createElement("span");
        placeholder.textContent = formPreviewModalImage.dataset.placeholder;
        formPreviewModalImage.appendChild(placeholder);
        return;
    }

    const image = new Image();
    image.onload = () => {
        formPreviewModalImage.innerHTML = "";
        formPreviewModalImage.style.backgroundImage = `url("${imageUrl}")`;
    };
    image.onerror = () => {
        const placeholder = document.createElement("span");
        formPreviewModalImage.innerHTML = "";
        formPreviewModalImage.style.backgroundImage = "";
        placeholder.textContent = formPreviewModalImage.dataset.placeholder;
        formPreviewModalImage.appendChild(placeholder);
    };
    image.src = imageUrl;
}

function openFormPreview(button) {
    const tvMode = button.dataset.previewMode === "tv";

    updateEventFormPreview();
    formPreviewModalMode.textContent = button.dataset.previewLabel;
    formPreviewModalCard.classList.toggle("admin-preview-modal-card--tv", tvMode);
    formPreviewModalCard.classList.toggle("admin-preview-modal-card--kiosk", !tvMode);
    formPreviewModalTitle.textContent = previewValue(previewFields.title, eventFormPreview.dataset.titlePlaceholder);
    formPreviewModalDate.textContent = previewValue(previewFields.eventDate, eventFormPreview.dataset.datePlaceholder);
    formPreviewModalPlace.textContent = previewValue(previewFields.place, eventFormPreview.dataset.placePlaceholder);
    formPreviewModalDescription.textContent = previewValue(previewFields.shortDescription, eventFormPreview.dataset.descriptionPlaceholder);
    setModalImage(currentPreviewImage);
    formPreviewModal.hidden = false;
}

function closeFormPreviewModal() {
    formPreviewModal.hidden = true;
}

if (eventFormPreview) {
    currentPreviewImage = previewTargets.images[0].dataset.initialImage || "";
    updateEventFormPreview();
    setPreviewImages(currentPreviewImage);

    [previewFields.title, previewFields.eventDate, previewFields.place, previewFields.shortDescription].forEach((field) => {
        if (field) {
            field.addEventListener("input", updateEventFormPreview);
        }
    });

    if (previewFields.image) {
        previewFields.image.addEventListener("change", () => {
            const file = previewFields.image.files[0];

            if (!file) {
                setPreviewImages(currentPreviewImage);
                return;
            }

            setPreviewImages(URL.createObjectURL(file));
        });
    }

    document.querySelectorAll("[data-open-form-preview]").forEach((button) => {
        button.addEventListener("click", () => openFormPreview(button));
    });
}

if (closeFormPreview) {
    closeFormPreview.addEventListener("click", closeFormPreviewModal);
}

if (formPreviewModal) {
    formPreviewModal.addEventListener("click", (event) => {
        if (event.target === formPreviewModal) {
            closeFormPreviewModal();
        }
    });
}

document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && formPreviewModal && !formPreviewModal.hidden) {
        closeFormPreviewModal();
    }
});
