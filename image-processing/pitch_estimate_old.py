import cv2
import numpy as np
from scipy.signal import find_peaks
from scipy.ndimage import gaussian_filter1d
import matplotlib.pyplot as plt
from dataclasses import dataclass
from typing import Tuple, List, Optional


@dataclass
class PitchResult:
    """Results from pitch estimation."""
    pitches_um: np.ndarray          # Individual pitch measurements
    mean_pitch_um: float            # Average pitch
    std_pitch_um: float             # Standard deviation
    num_wraps_detected: int         # Number of wrap sections found
    confidence: str                 # HIGH / MEDIUM / LOW
    bunching_detected: bool         # True if any section appears bunched
    

def estimate_pitch(
    image_path: str,
    scale_bar_um: float = 500,
    scale_bar_pixels: float = 100,
    fiber_thickness_um: Optional[float] = None,
    show_plots: bool = True
) -> PitchResult:
    """
    Estimate yarn pitch from microscopy image.
    
    Parameters
    ----------
    image_path : Path to the microscopy image
    scale_bar_um : Length of scale bar in micrometers
    scale_bar_pixels : Length of scale bar in pixels (measure from image)
    fiber_thickness_um : Known fiber thickness for bunching detection (optional)
    show_plots : Whether to display diagnostic plots
    
    Returns
    -------
    PitchResult with pitch measurements and quality info
    """
    
    # --- 1. Load and preprocess ---
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"Could not load image: {image_path}")
    
    # Calculate scale
    um_per_pixel = scale_bar_um / scale_bar_pixels
    
    # Enhance contrast
    img_enhanced = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8)).apply(img)
    
    # --- 2. Find thread axis angle ---
    edges = cv2.Canny(img_enhanced, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi/180, 50, minLineLength=50, maxLineGap=10)
    
    if lines is not None:
        angles = [np.arctan2(l[0][3]-l[0][1], l[0][2]-l[0][0]) for l in lines]
        axis_angle = np.median(angles) * 180 / np.pi
    else:
        axis_angle = 0  # Assume horizontal if detection fails
    
    # --- 3. Rotate so thread is horizontal ---
    h, w = img_enhanced.shape
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, axis_angle, 1.0)
    img_rotated = cv2.warpAffine(img_enhanced, M, (w, h))
    
    # --- 4. Create intensity profile along thread axis ---
    # Take middle strip and average vertically
    strip_height = h // 3
    y_start = h // 2 - strip_height // 2
    y_end = h // 2 + strip_height // 2
    strip = img_rotated[y_start:y_end, :]
    profile = np.mean(strip, axis=0)
    
    # Smooth the profile
    profile_smooth = gaussian_filter1d(profile, sigma=3)
    
    # --- 5. Find peaks (start of each bright wrap section) ---
    # Use gradient to find rising edges
    gradient = np.gradient(profile_smooth)
    
    # Find peaks in gradient (rising edges = start of wraps)
    min_distance = max(10, len(profile) // 100)  # Adaptive minimum distance
    peaks, properties = find_peaks(
        gradient,
        distance=min_distance,
        prominence=np.std(gradient) * 0.5
    )
    
    # --- 6. Calculate pitch (peak-to-peak distances) ---
    if len(peaks) < 2:
        return PitchResult(
            pitches_um=np.array([]),
            mean_pitch_um=0,
            std_pitch_um=0,
            num_wraps_detected=len(peaks),
            confidence="FAILED",
            bunching_detected=False
        )
    
    distances_px = np.diff(peaks)
    pitches_um = distances_px * um_per_pixel
    
    # Remove outliers (1.5 x IQR)
    q1, q3 = np.percentile(pitches_um, [25, 75])
    iqr = q3 - q1
    mask = (pitches_um >= q1 - 1.5*iqr) & (pitches_um <= q3 + 1.5*iqr)
    pitches_filtered = pitches_um[mask] if np.sum(mask) >= 2 else pitches_um
    
    mean_pitch = np.mean(pitches_filtered)
    std_pitch = np.std(pitches_filtered)
    cv = std_pitch / mean_pitch if mean_pitch > 0 else 1 #coeff of variation
    
    # --- 7. Confidence assessment ---
    if len(peaks) >= 5 and cv < 0.15:
        confidence = "HIGH"
    elif len(peaks) >= 3 and cv < 0.30:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"
    
    # --- 8. Bunching detection (if fiber thickness provided) ---
    bunching_detected = False
    if fiber_thickness_um is not None:
        # Check if any pitch is significantly larger than expected
        # (would indicate multiple fibers bunched together)
        bunching_detected = np.any(pitches_um > 1.8 * fiber_thickness_um)
    
    # --- 9. Visualization ---
    if show_plots:
        _plot_results(
            img, img_rotated, profile_smooth, gradient, peaks,
            pitches_um, mean_pitch, std_pitch, confidence,
            um_per_pixel, axis_angle
        )
    
    return PitchResult(
        pitches_um=pitches_um,
        mean_pitch_um=mean_pitch,
        std_pitch_um=std_pitch,
        num_wraps_detected=len(peaks),
        confidence=confidence,
        bunching_detected=bunching_detected
    )


def _plot_results(img, img_rotated, profile, gradient, peaks, 
                  pitches_um, mean_pitch, std_pitch, confidence,
                  um_per_pixel, axis_angle):
    """Create diagnostic visualization."""
    
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    
    # Original image
    axes[0, 0].imshow(img, cmap='gray')
    axes[0, 0].set_title(f'Original (detected axis: {axis_angle:.1f}°)')
    axes[0, 0].axis('off')
    
    # Rotated image with detected peaks marked
    axes[0, 1].imshow(img_rotated, cmap='gray')
    h = img_rotated.shape[0]
    for peak in peaks:
        axes[0, 1].axvline(x=peak, color='cyan', alpha=0.7, linewidth=1)
    axes[0, 1].set_title(f'Rotated + Detected Wraps (n={len(peaks)})')
    axes[0, 1].axis('off')
    
    # Intensity profile with peaks
    x_um = np.arange(len(profile)) * um_per_pixel
    axes[1, 0].plot(x_um, profile, 'b-', linewidth=1, label='Intensity')
    axes[1, 0].plot(x_um[peaks], profile[peaks], 'r^', markersize=8, label='Wrap starts')
    
    # Draw pitch arrows for first few measurements
    for i in range(min(3, len(peaks)-1)):
        x1, x2 = x_um[peaks[i]], x_um[peaks[i+1]]
        y = np.max(profile) * 1.05
        axes[1, 0].annotate('', xy=(x2, y), xytext=(x1, y),
                           arrowprops=dict(arrowstyle='<->', color='green', lw=2))
        axes[1, 0].text((x1+x2)/2, y*1.02, f'P={pitches_um[i]:.0f}μm', 
                       ha='center', fontsize=9, color='green')
    
    axes[1, 0].set_xlabel('Position (μm)')
    axes[1, 0].set_ylabel('Intensity')
    axes[1, 0].set_title('Intensity Profile Along Thread')
    axes[1, 0].legend()
    
    # Pitch distribution
    axes[1, 1].hist(pitches_um, bins=max(5, len(pitches_um)//3), 
                    color='steelblue', edgecolor='white', alpha=0.7)
    axes[1, 1].axvline(mean_pitch, color='red', linestyle='--', linewidth=2,
                       label=f'Mean: {mean_pitch:.1f} μm')
    axes[1, 1].axvspan(mean_pitch - std_pitch, mean_pitch + std_pitch, 
                       alpha=0.2, color='red', label=f'±1σ: {std_pitch:.1f} μm')
    axes[1, 1].set_xlabel('Pitch (μm)')
    axes[1, 1].set_ylabel('Count')
    axes[1, 1].set_title(f'Pitch Distribution (Confidence: {confidence})')
    axes[1, 1].legend()
    
    plt.tight_layout()
    plt.savefig('pitch_analysis_result.png', dpi=150, bbox_inches='tight')
    plt.show()
    
    # Print summary
    print("\n" + "="*50)
    print("PITCH ESTIMATION RESULTS")
    print("="*50)
    print(f"Wraps detected:    {len(peaks)}")
    print(f"Mean pitch:        {mean_pitch:.1f} μm")
    print(f"Std deviation:     {std_pitch:.1f} μm")
    print(f"Range:             {np.min(pitches_um):.1f} - {np.max(pitches_um):.1f} μm")
    print(f"Confidence:        {confidence}")
    print("="*50)


# =============================================================================
# USAGE
# =============================================================================

if __name__ == "__main__":
    # Example usage - update these values for your images
    
    # Measure scale bar from your image:
    # The scale bar shows 500μm - measure its length in pixels
    SCALE_BAR_UM = 500
    SCALE_BAR_PIXELS = 100  # <-- MEASURE THIS FROM YOUR IMAGE
    
    # Optional: known fiber thickness for bunching detection
    FIBER_THICKNESS_UM = None  # e.g., 25
    
    # Run on your image
    result = estimate_pitch(
        image_path="sample-images/Z50.jpg",
        scale_bar_um=SCALE_BAR_UM,
        scale_bar_pixels=SCALE_BAR_PIXELS,
        fiber_thickness_um=FIBER_THICKNESS_UM,
        show_plots=True
    )
    
    print(f"\nFinal estimate: {result.mean_pitch_um:.1f} ± {result.std_pitch_um:.1f} μm")