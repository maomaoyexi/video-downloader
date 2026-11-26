package io.github.maomaoyexi.videodownloader.prototype;

import com.yausername.youtubedl_android.YoutubeDLRequest;

import java.io.File;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.util.regex.Pattern;

final class DownloadCover {
    private static final String STEM = "cover";
    private static final Pattern COVER_FILE = Pattern.compile(STEM + "\\.(?:jpe?g|png|webp)", Pattern.CASE_INSENSITIVE);

    static final class Image {
        final File file;
        final String displayName;
        final String mimeType;

        private Image(File file, String displayName, String mimeType) {
            this.file = file;
            this.displayName = displayName;
            this.mimeType = mimeType;
        }
    }

    private DownloadCover() {}

    static void configure(YoutubeDLRequest request, File work) {
        request.addOption("--skip-download");
        request.addOption("--write-thumbnail");
        request.addOption("--ignore-no-formats-error");
        request.addOption("--socket-timeout", "8");
        request.addOption("--retries", "0");
        request.addOption("--extractor-retries", "0");
        // yt-dlp writes the image using the default template before moving it to its final path.
        String directory = work.getAbsolutePath().replace("%", "%%");
        request.addOption("-o", new File(directory, STEM + ".%(ext)s").getPath());
    }

    static Image find(File work, String savedMediaName) throws IOException {
        if (savedMediaName == null || savedMediaName.isEmpty()) throw new IOException("无法确认媒体文件名。");
        int extension = savedMediaName.lastIndexOf('.');
        String name = extension > 0 ? savedMediaName.substring(0, extension) : savedMediaName;

        File[] files = work.listFiles(file -> COVER_FILE.matcher(file.getName()).matches()
                && Files.isRegularFile(file.toPath(), LinkOption.NOFOLLOW_LINKS));
        if (files == null) throw new IOException("无法读取封面文件。");
        for (File file : files) {
            Image image = readImage(file, name);
            if (image != null) return image;
        }
        return null;
    }

    private static Image readImage(File file, String name) throws IOException {
        // The URL extension can differ from the response, and a network failure may leave a partial image.
        try (RandomAccessFile input = new RandomAccessFile(file, "r")) {
            long size = input.length();
            if (size < 12) return null;
            int first = input.readInt();
            if ((first >>> 8) == 0xffd8ff) {
                input.seek(size - 2);
                if (input.readUnsignedShort() == 0xffd9) return new Image(file, name + ".jpg", "image/jpeg");
            } else if (first == 0x89504e47 && input.readInt() == 0x0d0a1a0a && size >= 20) {
                input.seek(size - 12);
                if (input.readInt() == 0 && input.readInt() == 0x49454e44 && input.readInt() == 0xae426082) {
                    return new Image(file, name + ".png", "image/png");
                }
            } else if (first == 0x52494646) {
                long declaredSize = Integer.toUnsignedLong(Integer.reverseBytes(input.readInt()));
                if (declaredSize + 8 == size && input.readInt() == 0x57454250) {
                    return new Image(file, name + ".webp", "image/webp");
                }
            }
        }
        return null;
    }
}
