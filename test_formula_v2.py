"""Test the updated safest_weight formula."""

def test_updated_formula():
    """Test the new simplified formula"""
    
    print("=== NEW FORMULA TEST ===")
    print("Formula: weight = (length * road_penalty) / (safety_score + 1.0)")
    print("where safety_score = 100 - danger\n")
    
    # Test case 1: danger=44 vs danger=5 (both 100m roads)
    print("Test 1: Same length (100m), different danger")
    print("Road A: danger=44, length=100m")
    print("Road B: danger=5, length=100m")
    
    safety_44 = 100 - 44
    safety_5 = 100 - 5
    weight_44 = (100 * 10) / (safety_44 + 1.0)
    weight_5 = (100 * 10) / (safety_5 + 1.0)
    
    print(f"  Road A: safety={safety_44}, weight={weight_44:.2f}")
    print(f"  Road B: safety={safety_5}, weight={weight_5:.2f}")
    print(f"  Prefers: {'Road B [CORRECT]' if weight_5 < weight_44 else 'Road A [WRONG]'}\n")
    
    # Test case 2: danger=44 vs danger=5, but B is longer
    print("Test 2: Different length, different danger")
    print("Road A: danger=44, length=100m")
    print("Road B: danger=5, length=150m (slightly longer)")
    
    weight_44_100 = (100 * 10) / (safety_44 + 1.0)
    weight_5_150 = (150 * 10) / (safety_5 + 1.0)
    
    print(f"  Road A: danger=44, safety={safety_44}, length=100m -> weight={weight_44_100:.2f}")
    print(f"  Road B: danger=5, safety={safety_5}, length=150m -> weight={weight_5_150:.2f}")
    print(f"  Prefers: {'Road B [CORRECT]' if weight_5_150 < weight_44_100 else 'Road A [WRONG]'}\n")
    
    # Test the scale
    print("Test 3: Weight scaling across danger range")
    for d in [5, 20, 44, 60, 80, 95]:
        safety = 100 - d
        weight = (100 * 10) / (safety + 1.0)
        print(f"  danger={d:2d}: safety={safety:2d}, weight={weight:7.2f}")
    
    print("\nTest 4: Footpath vs Road with same danger")
    danger_val = 50
    safety_val = 100 - danger_val
    weight_footpath = (100 * 1) / (safety_val + 1.0)
    weight_road = (100 * 10) / (safety_val + 1.0)
    
    print(f"  Footpath (danger=50): weight={weight_footpath:.2f}")
    print(f"  Road (danger=50): weight={weight_road:.2f}")
    print(f"  Road penalty: {weight_road / weight_footpath:.1f}x")

if __name__ == '__main__':
    test_updated_formula()
