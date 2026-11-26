package io.github.maomaoyexi.videodownloader.prototype;

import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.StringReader;
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.regex.Pattern;

final class PlatformCookies {
    private static final int MAX_BYTES = 2 * 1024 * 1024;
    private static final String HEADER = "# Netscape HTTP Cookie File";
    private static final String HTTP_ONLY = "#HttpOnly_";
    private static final Pattern COOKIE_NAME = Pattern.compile("[!#$%&'*+.^_`|~0-9a-zA-Z-]+");
    private static final Pattern EXPIRY = Pattern.compile("(?:[0-9]+(?:\\.[0-9]+)?)?");
    private static final Pattern JOB_DIRECTORY = Pattern.compile(
            "job-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}");

    private PlatformCookies() {}

    enum Platform {
        BILIBILI("bilibili", "B 站", "bilibili.com"),
        YOUTUBE("youtube", "YouTube", "youtube.com");

        final String id;
        final String label;
        final Pattern domains;

        Platform(String id, String label, String domain) {
            this.id = id;
            this.label = label;
            domains = Pattern.compile("\\.?([a-z0-9-]+\\.)*" + Pattern.quote(domain), Pattern.CASE_INSENSITIVE);
        }

        static Platform fromId(String id) {
            for (Platform platform : values()) {
                if (platform.id.equals(id)) return platform;
            }
            return null;
        }

        File cookieFile(File directory) {
            return new File(directory, id + ".cookies.txt");
        }
    }

    static final class InvalidFile extends IOException {
        InvalidFile(String message) {
            super(message);
        }
    }

    static void install(String records, File destination) throws IOException {
        Path staging = stagingFile(destination).toPath();
        try {
            try (FileOutputStream out = new FileOutputStream(staging.toFile())) {
                out.write(records.getBytes(StandardCharsets.UTF_8));
                out.getFD().sync();
            }
            Files.move(staging, destination.toPath(),
                    StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
        } finally {
            Files.deleteIfExists(staging);
        }
    }

    static boolean remove(File installed) throws IOException {
        Files.deleteIfExists(stagingFile(installed).toPath());
        return Files.deleteIfExists(installed.toPath());
    }

    static void cleanStaleCopies(File installed, File cacheDir) {
        stagingFile(installed).delete();
        File[] jobDirs = cacheDir.listFiles(file -> JOB_DIRECTORY.matcher(file.getName()).matches()
                && file.isDirectory());
        if (jobDirs != null) {
            for (File jobDir : jobDirs) new File(jobDir, installed.getName()).delete();
        }
    }

    private static File stagingFile(File installed) {
        return new File(installed.getParentFile(), installed.getName() + ".new");
    }

    static String readRecords(InputStream source, Platform platform) throws IOException {
        if (source == null) throw new IOException();
        ByteArrayOutputStream file = new ByteArrayOutputStream();
        byte[] buffer = new byte[8192];
        for (int count; (count = source.read(buffer)) != -1; ) {
            if (file.size() + count > MAX_BYTES) {
                throw new InvalidFile("Cookie 文件不能超过 2 MB。");
            }
            file.write(buffer, 0, count);
        }
        String text;
        try {
            text = StandardCharsets.UTF_8.newDecoder().decode(ByteBuffer.wrap(file.toByteArray())).toString();
        } catch (CharacterCodingException error) {
            throw formatError();
        }
        if (text.startsWith("\uFEFF")) text = text.substring(1);

        try (BufferedReader reader = new BufferedReader(new StringReader(text))) {
            String header = reader.readLine();
            if (!HEADER.equals(header) && !"# HTTP Cookie File".equals(header)) throw formatError();
            StringBuilder result = new StringBuilder(HEADER).append('\n');
            for (String line; (line = reader.readLine()) != null; ) {
                boolean httpOnly = line.startsWith(HTTP_ONLY);
                if (line.trim().isEmpty() || (line.startsWith("#") && !httpOnly)) continue;
                String row = httpOnly ? line.substring(HTTP_ONLY.length()) : line;
                String[] fields = row.split("\\t", -1);
                if (fields[0].length() > 253 || !platform.domains.matcher(fields[0]).matches()) continue;
                if (!validRecord(fields)) throw formatError();
                result.append(line).append('\n');
            }
            if (result.length() == HEADER.length() + 1) {
                throw new InvalidFile("文件里没有 " + platform.label + " Cookie，请重新导出。");
            }
            return result.toString();
        }
    }

    private static boolean validRecord(String[] fields) {
        if (fields.length != 7
                || !(fields[0].startsWith(".") ? "TRUE" : "FALSE").equals(fields[1])
                || !fields[2].startsWith("/")
                || !("TRUE".equals(fields[3]) || "FALSE".equals(fields[3]))
                || !EXPIRY.matcher(fields[4]).matches()
                || !COOKIE_NAME.matcher(fields[5]).matches()) return false;
        return !fields[2].chars().anyMatch(Character::isISOControl)
                && !fields[6].chars().anyMatch(Character::isISOControl);
    }

    private static InvalidFile formatError() {
        return new InvalidFile("请选择 Netscape 格式的 cookies.txt，或重新导出 Cookie。");
    }
}
