const flashMessages = document.querySelectorAll("[data-flash-message]");

flashMessages.forEach((message) => {
    window.setTimeout(() => {
        message.classList.add("is-hiding");
    }, 3500);

    window.setTimeout(() => {
        message.remove();
    }, 4200);
});
