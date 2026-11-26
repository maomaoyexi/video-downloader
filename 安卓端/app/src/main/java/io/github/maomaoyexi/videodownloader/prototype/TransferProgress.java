package io.github.maomaoyexi.videodownloader.prototype;

import java.util.Locale;

final class TransferProgress {
    private static final String PREFIX = "[download] VD_PROGRESS ";
    static final String TEMPLATE = "download:" + PREFIX + "%(progress.status)s %(progress.downloaded_bytes)s "
            + "%(progress.total_bytes,progress.total_bytes_estimate)s %(progress.speed)s %(progress.eta)s";

    final float percent;
    final String speed;
    final int etaSeconds;

    private TransferProgress(float percent, String speed, int etaSeconds) {
        this.percent = percent;
        this.speed = speed;
        this.etaSeconds = etaSeconds;
    }

    static TransferProgress parse(String line) {
        if (!line.startsWith(PREFIX)) return null;
        String[] fields = line.substring(PREFIX.length()).trim().split("\\s+");
        if (fields.length != 5) return null;
        if ("finished".equals(fields[0])) return new TransferProgress(100, "", -1);
        if (!"downloading".equals(fields[0])) return null;

        double received = number(fields[1]);
        double total = number(fields[2]);
        float percent = received >= 0 && total > 0 ? (float) Math.min(100, received / total * 100) : -1;
        double rate = number(fields[3]);
        double eta = number(fields[4]);
        return new TransferProgress(percent, rate > 0 && percent < 100 ? formatSpeed(rate) : "",
                eta >= 0 && eta <= Integer.MAX_VALUE && percent < 100 ? (int) eta : -1);
    }

    private static double number(String value) {
        try {
            double parsed = Double.parseDouble(value);
            return Double.isFinite(parsed) && parsed >= 0 ? parsed : -1;
        } catch (NumberFormatException missing) {
            return -1;
        }
    }

    private static String formatSpeed(double bytesPerSecond) {
        if (bytesPerSecond >= 1024 * 1024) return String.format(Locale.ROOT, "%.2f MiB/s", bytesPerSecond / (1024 * 1024));
        if (bytesPerSecond >= 1024) return String.format(Locale.ROOT, "%.2f KiB/s", bytesPerSecond / 1024);
        return String.format(Locale.ROOT, "%.0f B/s", bytesPerSecond);
    }
}
