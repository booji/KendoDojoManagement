import { Link } from "react-router-dom"
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card"

// Members join by invite only (#472): there is no anonymous registration.
const RegisterPage = () => (
  <div className="flex min-h-screen items-center justify-center px-4 py-8">
    <Card className="w-full max-w-sm">
      <CardHeader>
        <CardTitle>Joining the dojo</CardTitle>
        <CardDescription>Accounts are by invitation</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <p className="text-sm">
          To create an account, ask your dojo for an invite. It comes as a link
          that sets up your passkey.
        </p>
        <p className="text-center text-sm text-muted-foreground">
          Already have an account?{" "}
          <Link to="/login" className="text-primary underline-offset-4 hover:underline">
            Sign in
          </Link>
        </p>
      </CardContent>
    </Card>
  </div>
)

export default RegisterPage
