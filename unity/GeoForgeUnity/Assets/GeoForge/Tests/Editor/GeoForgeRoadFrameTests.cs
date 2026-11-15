using NUnit.Framework;

namespace GeoForge.Tests
{
    public sealed class GeoForgeRoadFrameTests
    {
        [Test]
        public void CurvedRoadStationUsesOneHeightAcrossItsLocalFrame()
        {
            var profile=new GeoForgeRoadVerticalProfile{points=new[]{
                new[]{0d,0d,2d},new[]{10d,2d,3d},new[]{20d,0d,4d}}};
            var frame=new GeoForgeRoadFrame(profile,4);
            foreach(float z in new[]{-1.2f,2f,5.2f}) {
                Assert.That(frame.TryHeight(10,z,out float y),Is.True);
                Assert.That(y,Is.EqualTo(3).Within(0.00001));
            }
        }
        [Test]
        public void InclinedRibbonKeepsLongitudinalGradeButZeroCrossfall()
        {
            var frame=new GeoForgeRoadFrame(new GeoForgeRoadVerticalProfile{points=new[]{
                new[]{0d,0d,0d},new[]{100d,0d,10d}}},10);
            foreach(float z in new[]{-8f,0f,8f}) {
                Assert.That(frame.TryHeight(37,z,out float y),Is.True);
                Assert.That(y,Is.EqualTo(3.7).Within(0.00001));
            }
        }
    }
}
