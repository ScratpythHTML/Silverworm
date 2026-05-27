import cv2
import numpy as np
from scipy.signal import find_peaks
from scipy.ndimage import gaussian_filter, gaussian_filter1d
import matplotlib.pyplot as plt
from dataclasses import dataclass
import os

@dataclass 
class PitchResult:
    pitches_um: np.ndarray
    mean_pitch_um: float
    std_pitch_um: float
    num_wraps: int
    confidence: str
    scale_um_per_px: float
    texture_angle_deg: float
    thread_angle_deg: float

def auto_detect_scale_bar(img_color: np.ndarray, expected_um: float = 500) -> float:
    """Auto-detect blue scale bar and return μm per pixel."""
    h, w = img_color.shape[:2]
    hsv = cv2.cvtColor(img_color, cv2.COLOR_BGR2HSV)
    blue_mask = cv2.inRange(hsv, (100, 80, 100), (130, 255, 255))
    contours, _ = cv2.findContours(blue_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    best_width = None
    for cnt in contours:
        x, y, cw, ch = cv2.boundingRect(cnt)
        aspect = cw / max(ch, 1)
        if cw > 50 and aspect > 4 and y < h // 3:
            if best_width is None or cw > best_width:
                best_width = cw
    
    if best_width is not None:
        um_per_px = expected_um / best_width
        print(f"  Scale bar: {best_width}px = {expected_um}μm → {um_per_px:.3f} μm/px")
        return um_per_px
    
    print("  WARNING: Scale bar not detected, using default 2.0 μm/px")
    return 2.0

def compute_wrap_angle(img: np.ndarray, sigma: float = 3.0) -> float:
    """
    Compute wrap angle using combined approach.
    Returns the TEXTURE direction angle in degrees.
    The actual FIBER angle will be perpendicular to this.
    """
    
    # Method 1: Hough lines - look for diagonal lines
    edges = cv2.Canny(img, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi/180, 30, 
                            minLineLength=30, maxLineGap=10)
    
    hough_angle = None
    if lines is not None:
        angles = []
        lengths = []
        
        for line in lines:
            x1, y1, x2, y2 = line[0]
            angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
            length = np.sqrt((x2-x1)**2 + (y2-y1)**2)
            
            # Keep diagonal lines (20-70° from horizontal, either direction)
            abs_angle = abs(angle)
            if 20 < abs_angle < 70:
                angles.append(angle)
                lengths.append(length)
        
        if len(angles) >= 5:
            angles = np.array(angles)
            lengths = np.array(lengths)
            hough_angle = np.average(angles, weights=lengths)
    
    # Method 2: Structure tensor on interior
    thread_mask = img > np.percentile(img, 50)
    kernel = np.ones((10, 10), np.uint8)
    interior_mask = cv2.erode(thread_mask.astype(np.uint8), kernel, iterations=1)
    
    tensor_angle = None
    if np.sum(interior_mask) > 500:
        img_float = img.astype(np.float64)
        Ix = cv2.Sobel(img_float, cv2.CV_64F, 1, 0, ksize=3)
        Iy = cv2.Sobel(img_float, cv2.CV_64F, 0, 1, ksize=3)
        
        Ixx = gaussian_filter(Ix * Ix, sigma=sigma)
        Iyy = gaussian_filter(Iy * Iy, sigma=sigma)
        Ixy = gaussian_filter(Ix * Iy, sigma=sigma)
        
        orientation = 0.5 * np.arctan2(2 * Ixy, Ixx - Iyy)
        trace = Ixx + Iyy
        det_term = np.sqrt((Ixx - Iyy)**2 + 4 * Ixy**2)
        coherence = det_term / (trace + 1e-10)
        
        valid = (interior_mask > 0) & (coherence > 0.3)
        
        if np.sum(valid) > 100:
            weights = coherence[valid]
            angles_t = orientation[valid]
            sin_sum = np.sum(np.sin(2 * angles_t) * weights)
            cos_sum = np.sum(np.cos(2 * angles_t) * weights)
            tensor_angle = np.degrees(0.5 * np.arctan2(sin_sum, cos_sum))
    
    # Combine results - prefer diagonal angles
    final_angle = None
    
    if hough_angle is not None and abs(hough_angle) > 20:
        final_angle = hough_angle
    elif tensor_angle is not None and abs(tensor_angle) > 20:
        final_angle = tensor_angle
    
    # If we didn't find good diagonal angles, use default
    if final_angle is None:
        final_angle = -45.0
    
    # CRITICAL FIX: Structure tensor finds gradient direction (perpendicular to fibers)
    # We need the FIBER direction, so add 90°
    # Also NEGATE because image Y-axis is inverted
    fiber_angle = (final_angle + 90.0)
    
    # Normalize to -90 to +90 range
    if fiber_angle > 90:
        fiber_angle -= 180
    elif fiber_angle < -90:
        fiber_angle += 180
        
    return fiber_angle


def estimate_pitch(image_path: str, show_plots: bool = True,
                   output_dir: str = ".") -> PitchResult:
    """
    Estimate yarn pitch with wrap-angle-aligned detection lines.
    """
    
    # === STEP 1: Load and enhance ===
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    img_color = cv2.imread(image_path)
    
    if img is None:
        raise FileNotFoundError(f"Could not load: {image_path}")
    
    fname = os.path.basename(image_path)
    print(f"\nProcessing: {fname}")
    
    um_per_px = auto_detect_scale_bar(img_color)
    
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    img_enhanced = clahe.apply(img)
    
    # === STEP 2: Detect thread axis angle, rotate horizontal ===
    edges = cv2.Canny(img_enhanced, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi/180, 50, minLineLength=80, maxLineGap=20)
    
    thread_angle = 0
    if lines is not None:
        angles = [np.arctan2(l[0][3]-l[0][1], l[0][2]-l[0][0]) for l in lines]
        angles = [a for a in angles if abs(a) < np.pi/4]
        if angles:
            thread_angle = np.degrees(np.median(angles))
    
    h, w = img_enhanced.shape
    M = cv2.getRotationMatrix2D((w//2, h//2), thread_angle, 1.0)
    img_rot = cv2.warpAffine(img_enhanced, M, (w, h))
    img_color_rot = cv2.warpAffine(img_color, M, (w, h))
    
    # === STEP 3: Detect wrap angle ===
    wrap_angle = compute_wrap_angle(img_rot, sigma=3.0)
    
    print(f"  Thread axis: {thread_angle:.1f}°, Wrap angle: {wrap_angle:.1f}°")
    
    # === STEP 4: Create 1D intensity profile ===
    strip_h = h // 3
    y1, y2 = h//2 - strip_h//2, h//2 + strip_h//2
    strip = img_rot[y1:y2, :]
    profile = np.mean(strip, axis=0)
    
    # === STEP 5: Smooth and find peaks ===
    sigma = 5
    min_dist_px = 40
    prom_factor = 0.08
    
    profile_smooth = gaussian_filter1d(profile, sigma=sigma)
    prominence = (np.max(profile_smooth) - np.min(profile_smooth)) * prom_factor
    
    peaks, _ = find_peaks(profile_smooth, distance=min_dist_px, prominence=prominence)
    
    # === STEP 6: Calculate pitch ===
    if len(peaks) < 2:
        return PitchResult(np.array([]), 0, 0, len(peaks), "FAILED", 
                          um_per_px, wrap_angle, thread_angle)
    
    distances_px = np.diff(peaks)
    pitches_um = distances_px * um_per_px
    
    # Remove outliers
    if len(pitches_um) >= 4:
        q1, q3 = np.percentile(pitches_um, [25, 75])
        iqr = q3 - q1
        mask = (pitches_um >= q1 - 1.5*iqr) & (pitches_um <= q3 + 1.5*iqr)
        pitches_clean = pitches_um[mask] if np.sum(mask) >= 2 else pitches_um
    else:
        pitches_clean = pitches_um
    
    mean_pitch = np.mean(pitches_clean)
    std_pitch = np.std(pitches_clean)
    cv = std_pitch / mean_pitch if mean_pitch > 0 else 1
    
    if len(peaks) >= 10 and cv < 0.20:
        confidence = "HIGH"
    elif len(peaks) >= 5 and cv < 0.35:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"
    
    print(f"  Detected {len(peaks)} wraps, pitch: {mean_pitch:.1f} ± {std_pitch:.1f} μm")
    
    # === Visualization with ANGLED lines ===
    if show_plots:
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        fig.suptitle(f'Pitch Analysis: {fname}', fontsize=14, fontweight='bold')
        
        # Original
        axes[0,0].imshow(cv2.cvtColor(img_color, cv2.COLOR_BGR2RGB))
        axes[0,0].set_title(f'Original (thread axis: {thread_angle:.1f}°)')
        axes[0,0].axis('off')
        
        # Rotated with ANGLED detection lines
        vis = img_color_rot.copy()
        
        # wrap_angle is already the FIBER direction (from compute_wrap_angle)
        # Lines marking wraps should be PARALLEL to fiber direction
        line_rad = np.radians(wrap_angle)
        line_half_len = strip_h // 2 + 20  # Half length of each line
        
        # Draw lines parallel to fiber direction through each detected peak
        for pk in peaks:
            # Center point of line
            cx = pk
            cy = h // 2
            
            # Line endpoints using fiber angle (parallel to wraps)
            dx = int(line_half_len * np.cos(line_rad))
            dy = int(line_half_len * np.sin(line_rad))
            
            pt1 = (cx - dx, cy - dy)
            pt2 = (cx + dx, cy + dy)
            
            cv2.line(vis, pt1, pt2, (0, 255, 0), 2)
        
        # Draw pitch arrows
        for i in range(min(5, len(peaks)-1)):
            x1, x2 = peaks[i], peaks[i+1]
            y_arr = y1 - 25
            cv2.arrowedLine(vis, (x1, y_arr), (x2, y_arr), (0, 255, 255), 2)
            cv2.putText(vis, f'{pitches_um[i]:.0f}um',
                       ((x1+x2)//2 - 30, y_arr - 8),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
        
        axes[0,1].imshow(cv2.cvtColor(vis, cv2.COLOR_BGR2RGB))
        axes[0,1].set_title(f'Detected Wraps (n={len(peaks)}, fiber angle: {wrap_angle:.1f}°)')
        axes[0,1].axis('off')
        
        # Profile
        x_um = np.arange(len(profile_smooth)) * um_per_px
        axes[1,0].plot(x_um, profile_smooth, 'b-', lw=1.5, label='Intensity')
        axes[1,0].plot(x_um[peaks], profile_smooth[peaks], 'r^', ms=8, label='Wraps')
        axes[1,0].set_xlabel('Position (μm)')
        axes[1,0].set_ylabel('Intensity')
        axes[1,0].set_title('Intensity Profile Along Thread')
        axes[1,0].legend()
        axes[1,0].grid(True, alpha=0.3)
        
        # Histogram
        if len(pitches_um) >= 2:
            axes[1,1].hist(pitches_um, bins=max(3, len(pitches_um)//2),
                          color='steelblue', edgecolor='white', alpha=0.7)
            axes[1,1].axvline(mean_pitch, color='red', ls='--', lw=2,
                             label=f'Mean: {mean_pitch:.1f} μm')
            axes[1,1].axvspan(mean_pitch-std_pitch, mean_pitch+std_pitch,
                             alpha=0.2, color='red', label=f'±σ: {std_pitch:.1f} μm')
            axes[1,1].legend()
        axes[1,1].set_xlabel('Pitch (μm)')
        axes[1,1].set_ylabel('Count')
        axes[1,1].set_title(f'Pitch Distribution | Confidence: {confidence}')
        
        summary = f"Mean Pitch: {mean_pitch:.1f} ± {std_pitch:.1f} μm | Wraps: {len(peaks)} | Texture∠: {wrap_angle:.1f}° | Confidence: {confidence}"
        fig.text(0.5, 0.02, summary, ha='center', fontsize=11,
                bbox=dict(boxstyle='round', facecolor='lightgreen', alpha=0.8))
        
        plt.tight_layout(rect=[0, 0.05, 1, 0.95])
        out_path = os.path.join(output_dir, f'pitch_result_{fname.replace(".jpg",".png")}')
        plt.savefig(out_path, dpi=150, bbox_inches='tight')
        plt.close()
        print(f"  Saved: {out_path}")
    
    return PitchResult(pitches_um, mean_pitch, std_pitch, len(peaks), confidence, 
                      um_per_px, wrap_angle, thread_angle)


def run_batch(image_paths: list, output_dir: str = "."):
    """Process multiple images."""
    print("\n" + "="*80)
    print("YARN PITCH ESTIMATION - WRAP ANGLE ALIGNED")
    print("="*80)
    
    results = []
    for path in image_paths:
        r = estimate_pitch(path, show_plots=True, output_dir=output_dir)
        results.append((os.path.basename(path), r))
    
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    print(f"{'Image':<18} {'Mean Pitch':>12} {'Std Dev':>10} {'Wraps':>6} {'Texture∠':>10} {'Conf':>10}")
    print("-"*80)
    
    for fname, r in results:
        print(f"{fname:<18} {r.mean_pitch_um:>10.1f} μm {r.std_pitch_um:>8.1f} μm "
              f"{r.num_wraps:>6} {r.texture_angle_deg:>9.1f}° {r.confidence:>10}")
    
    print("="*80)
    return results


if __name__ == "__main__":
    images = [
        "sample-images/Z50.jpg",
        "sample-images/Z100.jpg",
        "sample-images/Z150.jpg"
    ]
    run_batch(images, output_dir="results")