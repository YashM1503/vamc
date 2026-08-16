real(kind=8) function clamp(x)
  real(kind=8), intent(in) :: x
  if (x .lt. 0.0d0) then
    clamp = abs(x)
  else
    clamp = sqrt(x)
  end if
end function clamp
