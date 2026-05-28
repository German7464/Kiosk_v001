const adminPreviewForm = document.querySelector("[data-admin-preview-form]");
const adminPreviewModal = document.querySelector("[data-admin-preview-modal]");
const adminPreviewModalMode = document.querySelector("[data-admin-preview-modal-mode]");
const adminPreviewModalCard = document.querySelector("[data-admin-preview-modal-card]");
const adminPreviewModalImage = document.querySelector("[data-admin-preview-modal-image]");
const adminPreviewModalTitle = document.querySelector("[data-admin-preview-modal-title]");
const adminPreviewModalDate = document.querySelector("[data-admin-preview-modal-date]");
const adminPreviewModalPlace = document.querySelector("[data-admin-preview-modal-place]");
const adminPreviewModalDescription = document.querySelector("[data-admin-preview-modal-description]");
const adminPreviewClose = document.querySelector("[data-admin-preview-close]");
const adminPreviewItems = document.querySelectorAll("[data-admin-preview]");
const adminPreviewFields = {
    title: document.querySelector("[data-event-preview-field='title']"),
    eventDate: document.querySelector("[data-event-preview-field='event_date']"),
    place: document.querySelector("[data-event-preview-field='place']"),
    shortDescription: document.querySelector("[data-event-preview-field='short_description']"),
    image: document.querySelector("[data-event-preview-field='image']"),
};
let adminPreviewSavedImage = "";
let adminPreviewSelectedImage = "";

function adminPreviewPlaceholderText(media) {
    if (media && media.dataset.placeholder) {
        return media.dataset.placeholder;
    }

    if (adminPreviewForm) {
        return adminPreviewForm.dataset.imagePlaceholder;
    }

    return "Image area";
}

function setAdminPreviewPlaceholder(media) {
    const placeholder = document.createElement("span");
    media.innerHTML = "";
    media.style.backgroundImage = "";
    placeholder.className = "admin-event-preview__placeholder";
    placeholder.textContent = adminPreviewPlaceholderText(media);
    media.appendChild(placeholder);
}

function setAdminPreviewImage(media, imageUrl) {
    media.innerHTML = "";
    media.style.backgroundImage = "";
    media.style.backgroundPosition = "center";
    media.style.backgroundRepeat = "no-repeat";
    media.style.backgroundSize = "cover";

    if (!imageUrl) {
        setAdminPreviewPlaceholder(media);
        return;
    }

    const image = new Image();
    image.onload = () => {
        media.innerHTML = "";
        media.style.backgroundImage = `url("${imageUrl}")`;
    };
    image.onerror = () => {
        setAdminPreviewPlaceholder(media);
    };
    image.src = imageUrl;
}

function adminPreviewValue(field, placeholder) {
    return field && field.value.trim() ? field.value.trim() : placeholder;
}

function setAdminPreviewText(item, key, text) {
    item.dataset[`preview${key}`] = text;
    item.querySelectorAll(`[data-form-preview-${key.toLowerCase()}]`).forEach((target) => {
        target.textContent = text;
    });
}

function updateAdminFormPreviewText() {
    if (!adminPreviewForm) {
        return;
    }

    const values = {
        Title: adminPreviewValue(adminPreviewFields.title, adminPreviewForm.dataset.titlePlaceholder),
        Date: adminPreviewValue(adminPreviewFields.eventDate, adminPreviewForm.dataset.datePlaceholder),
        Place: adminPreviewValue(adminPreviewFields.place, adminPreviewForm.dataset.placePlaceholder),
        Description: adminPreviewValue(adminPreviewFields.shortDescription, adminPreviewForm.dataset.descriptionPlaceholder),
    };

    adminPreviewItems.forEach((item) => {
        if (!item.closest("[data-admin-preview-form]")) {
            return;
        }

        Object.entries(values).forEach(([key, value]) => {
            setAdminPreviewText(item, key, value);
        });
    });
}

function setAdminFormPreviewImage(imageUrl) {
    adminPreviewSelectedImage = imageUrl || "";

    adminPreviewItems.forEach((item) => {
        if (!item.closest("[data-admin-preview-form]")) {
            return;
        }

        item.dataset.previewImage = adminPreviewSelectedImage;
        setAdminPreviewImage(item.querySelector("[data-admin-preview-media]"), adminPreviewSelectedImage);
    });
}

function adminPreviewData(item) {
    return {
        mode: item.dataset.previewMode || "kiosk",
        label: item.dataset.previewLabel || "",
        title: item.dataset.previewTitle || "",
        date: item.dataset.previewDate || "",
        place: item.dataset.previewPlace || "",
        description: item.dataset.previewDescription || "",
        image: item.dataset.previewImage || "",
    };
}

function openAdminPreview(item) {
    if (adminPreviewForm) {
        updateAdminFormPreviewText();
    }

    const preview = adminPreviewData(item);
    const tvMode = preview.mode === "tv";

    adminPreviewModalMode.textContent = preview.label;
    adminPreviewModalCard.classList.toggle("admin-event-preview-modal__card--tv", tvMode);
    adminPreviewModalCard.classList.toggle("admin-event-preview-modal__card--kiosk", !tvMode);
    adminPreviewModalTitle.textContent = preview.title;
    adminPreviewModalDate.textContent = preview.date;
    adminPreviewModalPlace.textContent = preview.place;
    adminPreviewModalDescription.textContent = preview.description;
    setAdminPreviewImage(adminPreviewModalImage, preview.image);
    adminPreviewModal.hidden = false;
}

function closeAdminPreviewModal() {
    if (adminPreviewModal) {
        adminPreviewModal.hidden = true;
    }
}

adminPreviewItems.forEach((item) => {
    const media = item.querySelector("[data-admin-preview-media]");
    const image = media ? media.querySelector("img") : null;
    const imageUrl = item.dataset.previewImage || (image ? image.src : "");

    if (media) {
        setAdminPreviewImage(media, imageUrl);
    }

    item.querySelectorAll("[data-admin-preview-open]").forEach((button) => {
        button.addEventListener("click", (event) => {
            event.stopPropagation();
            openAdminPreview(item);
        });
    });

    if (item.matches("[data-admin-preview-open]")) {
        item.addEventListener("click", () => openAdminPreview(item));
    }
});

if (adminPreviewForm) {
    adminPreviewSavedImage = adminPreviewItems[0] ? adminPreviewItems[0].dataset.previewImage || "" : "";
    adminPreviewSelectedImage = adminPreviewSavedImage;
    updateAdminFormPreviewText();

    [adminPreviewFields.title, adminPreviewFields.eventDate, adminPreviewFields.place, adminPreviewFields.shortDescription].forEach((field) => {
        if (field) {
            field.addEventListener("input", updateAdminFormPreviewText);
        }
    });

    if (adminPreviewFields.image) {
        adminPreviewFields.image.addEventListener("change", () => {
            const file = adminPreviewFields.image.files[0];
            setAdminFormPreviewImage(file ? URL.createObjectURL(file) : adminPreviewSavedImage);
        });
    }
}

if (adminPreviewClose) {
    adminPreviewClose.addEventListener("click", closeAdminPreviewModal);
}

if (adminPreviewModal) {
    adminPreviewModal.addEventListener("click", (event) => {
        if (event.target === adminPreviewModal) {
            closeAdminPreviewModal();
        }
    });
}

document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && adminPreviewModal && !adminPreviewModal.hidden) {
        closeAdminPreviewModal();
    }
});
