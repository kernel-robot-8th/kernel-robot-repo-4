"""Diagnose printed-box visibility from RGB features without simulator object coordinates."""

import cv2
import numpy as np

from .common import PACKAGE


class PrintedBoxDetector:
    """Match real lid prints with SIFT and a checked homography, only as a diagnostic."""

    def __init__(self):
        """Extract feature descriptors from the two attributed recorded lid textures."""
        self.sift = cv2.SIFT_create(nfeatures=1200, contrastThreshold=0.01)
        self.matcher = cv2.BFMatcher()
        self.templates = []
        for name in ["lid_two", "lid_one"]:
            gray = cv2.imread(str(PACKAGE / f"config/textures/{name}.png"), cv2.IMREAD_GRAYSCALE)
            points, descriptors = self.sift.detectAndCompute(gray, None)
            self.templates.append((name, gray.shape, points, descriptors))

    def detect(self, rgb):
        """Require multiple local feature matches and geometric consistency, or return unknown."""
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        points, descriptors = self.sift.detectAndCompute(gray, None)
        best = {
            "detected": False,
            "inliers": 0,
            "matches": 0,
            "method": "RGB SIFT+RANSAC; diagnostic, not ACT/CNN input",
        }
        if descriptors is None or len(points) < 8:
            return best
        for name, shape, source, desc in self.templates:
            candidates = self.matcher.knnMatch(desc, descriptors, k=2)
            good = [
                a for pair in candidates if len(pair) == 2 for a, b in [pair] if a.distance < 0.7 * b.distance
            ]
            if len(good) < 8:
                continue
            first = np.float32([source[m.queryIdx].pt for m in good])
            second = np.float32([points[m.trainIdx].pt for m in good])
            matrix, inliers = cv2.findHomography(first, second, cv2.RANSAC, 3)
            if matrix is None:
                continue
            count = int(inliers.sum())
            height, width = shape
            quad = cv2.perspectiveTransform(
                np.float32([[[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]]]), matrix
            )[0]
            area = abs(cv2.contourArea(quad))
            valid = (
                count >= 6
                and count / len(good) >= 0.35
                and cv2.isContourConvex(quad)
                and 200 < area < rgb.shape[0] * rgb.shape[1] * 0.8
            )
            if (valid, count) > (best["detected"], best["inliers"]):
                best = {
                    "detected": bool(valid),
                    "inliers": count,
                    "matches": len(good),
                    "template": name,
                    "polygon": quad.tolist(),
                    "method": best["method"],
                }
        if not best["detected"]:
            lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
            hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
            mask = (
                (lab[:, :, 0] > 150)
                & (lab[:, :, 1] > 130)
                & (lab[:, :, 2] > 120)
                & (lab[:, :, 2] < 140)
                & (hsv[:, :, 1] > 15)
                & (hsv[:, :, 1] < 80)
            ).astype(np.uint8) * 255
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            candidates = []
            for contour in contours:
                area = cv2.contourArea(contour)
                x, y, width, height = cv2.boundingRect(contour)
                hull = cv2.convexHull(contour)
                solidity = area / max(1, cv2.contourArea(hull))
                if (
                    2000 < area < 50000
                    and 0.5 < width / height < 2.5
                    and solidity > 0.85
                    and min(x, y) > 3
                    and x + width < rgb.shape[1] - 3
                    and y + height < rgb.shape[0] - 3
                ):
                    candidates.append((area, contour))
            if candidates:
                _, contour = max(candidates, key=lambda value: value[0])
                polygon = cv2.boxPoints(cv2.minAreaRect(contour))
                best = {
                    "detected": True,
                    "inliers": 0,
                    "matches": 0,
                    "template": "pink_lid_color_region",
                    "polygon": polygon.tolist(),
                    "method": "RGB pink-cap color region with area, shape and border checks; diagnostic only",
                }
        return best


def annotated(rgb, result):
    """Mark only geometrically accepted detections for human review, keeping raw inputs separate."""
    image = rgb.copy()
    if result["detected"]:
        cv2.polylines(image, [np.int32(result["polygon"])], True, (45, 210, 100), 3)
    text = f"print match: {result['inliers']} inliers / {'detected' if result['detected'] else 'unknown'}"
    cv2.putText(image, text, (12, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (30, 150, 60), 2)
    return image
