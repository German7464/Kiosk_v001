package org.kiosk.harness.core;

import java.io.IOException;

/** Android JSONTokener accepts comments/single quotes/trailing data; cache preflight does not. */
final class JsonSyntax {
    private final String text;
    private int position;
    private JsonSyntax(String text) { this.text = text; }
    static void validate(String text) throws IOException {
        JsonSyntax parser = new JsonSyntax(text);
        parser.value(0);
        parser.space();
        if (parser.position != text.length()) throw invalid();
    }
    private void value(int depth) throws IOException {
        space();
        char c = peek();
        if (c == '{' || c == '[') {
            if (depth >= 32) throw invalid();
            position++;
            char end = c == '{' ? '}' : ']';
            space();
            if (peek() == end) { position++; return; }
            while (true) {
                if (c == '{') { string(); space(); take(':'); }
                value(depth + 1); space();
                if (peek() == end) { position++; return; }
                take(','); space();
            }
        }
        if (c == '"') { string(); return; }
        for (String literal : new String[]{"true", "false", "null"}) {
            if (text.startsWith(literal, position)) { position += literal.length(); return; }
        }
        if (c == '-') position++;
        if (peek() == '0') position++;
        else digits(true);
        if (peek() == '.') { position++; digits(true); }
        if (peek() == 'e' || peek() == 'E') {
            position++;
            if (peek() == '+' || peek() == '-') position++;
            digits(true);
        }
    }
    private void digits(boolean required) throws IOException {
        int start = position;
        while (peek() >= '0' && peek() <= '9') position++;
        if (required && start == position) throw invalid();
    }
    private void string() throws IOException {
        space(); take('"');
        while (true) {
            if (position >= text.length()) throw invalid();
            char c = text.charAt(position++);
            if (c == '"') return;
            if (c < 32) throw invalid();
            if (c == '\\') {
                if (position >= text.length()) throw invalid();
                c = text.charAt(position++);
                if (c == 'u') {
                    for (int n = 0; n < 4; n++) {
                        if (position >= text.length() || Character.digit(text.charAt(position++), 16) < 0) throw invalid();
                    }
                } else if ("\"\\/bfnrt".indexOf(c) < 0) throw invalid();
            }
        }
    }
    private char peek() { return position < text.length() ? text.charAt(position) : '\0'; }
    private void space() { while (" \t\r\n".indexOf(peek()) >= 0 && position < text.length()) position++; }
    private void take(char c) throws IOException { if (peek() != c) throw invalid(); position++; }
    private static IOException invalid() { return new IOException("invalid_local_view"); }
}
