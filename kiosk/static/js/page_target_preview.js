"use strict";

(() => {
    const surface = document.getElementById("page-display");
    const preview = document.getElementById("page-preview-data");
    try {
        window.KioskPageDisplay.mount(surface, JSON.parse(preview.textContent));
    } catch (error) {
        surface.textContent = "This draft preview could not be displayed.";
    }
})();
