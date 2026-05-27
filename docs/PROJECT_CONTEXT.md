# Project Context

## Purpose

Kiosk_v001 is a local event display system for a diploma project. It lets administrators manage event cards and display them on local kiosk, TV, and preview screens.

## Target Devices

- Touch kiosks
- Smart TV screens
- Preview screens
- Admin workstation browser

## Main Routes

- `/kiosk` for kiosk display mode
- `/kiosk/events` for kiosk event cards
- `/tv` for TV display mode
- `/preview` for preview display mode
- `/admin` for administration
- `/api/version` for client update checks

## System Idea

The system runs on a local server. Clients open display routes in a browser and periodically check the content version. Admin changes update the stored content and version so kiosk, TV, and preview clients can refresh without requiring a cloud service.
