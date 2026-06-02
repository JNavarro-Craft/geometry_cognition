using SAP2000v1;

namespace RhinoSAP.SAP
{
    public static class SapModelExtensions
    {
        public static bool IsValid(this cSapModel model)
        {
            if (model == null)
                return false;

            try
            {
                model.GetModelIsLocked();
                return true;
            }
            catch
            {
                return false;
            }
        }
    }
}
